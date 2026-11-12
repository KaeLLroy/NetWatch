"""Safe network diagnostics: ping, DNS, traceroute, and connectivity tests."""

from __future__ import annotations

import ipaddress
import locale
import os
import re
import subprocess
import time
from typing import Any

import dns.exception
import dns.resolver

from ..config import ValidationError
from .connectivity import connectivity_targets

HOSTNAME_PATTERN = re.compile(
    r"^(?=.{1,253}\.?$)(?!-)[A-Za-z0-9-]{1,63}(?<!-)"
    r"(?:\.(?!-)[A-Za-z0-9-]{1,63}(?<!-))*\.?$"
)
TIME_PATTERN = re.compile(r"time\s*[=<]{1,2}\s*([\d.]+)\s*ms", re.IGNORECASE)
PING_SUMMARY = re.compile(
    r"Sent\s*=\s*(\d+).*?Received\s*=\s*(\d+).*?Lost\s*=\s*(\d+)\s*\((\d+)%",
    re.IGNORECASE | re.DOTALL,
)
DNS_TYPES = {"A", "AAAA", "CNAME", "MX", "NS", "TXT"}
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def validate_target(raw: Any) -> str:
    """Accept only a literal IP address or a strict RFC-1123 hostname."""
    if not isinstance(raw, str):
        raise ValidationError("Target must be a hostname or IP address.")
    value = raw.strip()
    if not value or len(value) > 253:
        raise ValidationError("Target must be between 1 and 253 characters.")
    if value.startswith("-"):
        raise ValidationError("Target must not start with a hyphen.")
    if any(character.isspace() or ord(character) < 32 for character in value):
        raise ValidationError("Target must not contain whitespace or control characters.")
    if "%" in value:
        raise ValidationError("Scoped IPv6 addresses are not supported.")

    try:
        return str(ipaddress.ip_address(value))
    except ValueError:
        pass

    if re.fullmatch(r"[0-9.]+", value):
        raise ValidationError("Target is not a valid IPv4 address.")
    if not HOSTNAME_PATTERN.fullmatch(value):
        raise ValidationError("Target is not a valid hostname or IP address.")
    return value.lower().rstrip(".") or value.lower()


def _decode(data: bytes) -> str:
    if not data:
        return ""
    for encoding in (locale.getpreferredencoding(False), "utf-8", "cp850", "cp437"):
        try:
            return data.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return data.decode("utf-8", errors="replace")


def _run(args: list[str], timeout: float) -> tuple[str, int, float, bool]:
    started = time.perf_counter()
    kwargs: dict[str, Any] = {
        "capture_output": True,
        "timeout": timeout,
        "check": False,
    }
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        completed = subprocess.run(args, **kwargs)  # noqa: S603 - args are validated, shell=False
    except subprocess.TimeoutExpired as exc:
        output = _decode(exc.stdout or b"") + _decode(exc.stderr or b"")
        return output, -1, round((time.perf_counter() - started) * 1000, 1), True
    except FileNotFoundError as exc:
        raise RuntimeError(f"Required Windows tool not found: {args[0]}") from exc
    output = _decode(completed.stdout) + _decode(completed.stderr)
    return (
        output.strip(),
        completed.returncode,
        round((time.perf_counter() - started) * 1000, 1),
        False,
    )


def parse_ping_output(output: str, expected: int = 4) -> dict[str, Any]:
    times = [float(value) for value in TIME_PATTERN.findall(output)]
    summary = PING_SUMMARY.search(output)
    if summary:
        sent, received, _lost, loss = (int(group) for group in summary.groups())
    else:
        sent = expected
        received = len(re.findall(r"TTL[=\s]", output, re.IGNORECASE))
        loss = round((sent - received) * 100 / sent) if sent else 100

    stats = re.search(
        r"Minimum\s*=\s*([\d.]+)\s*ms.*?Maximum\s*=\s*([\d.]+)\s*ms.*?Average\s*=\s*([\d.]+)\s*ms",
        output,
        re.IGNORECASE | re.DOTALL,
    )
    if stats:
        minimum, maximum, average = (float(value) for value in stats.groups())
    elif times:
        minimum, maximum = min(times), max(times)
        average = round(sum(times) / len(times), 1)
    else:
        minimum = maximum = average = None

    return {
        "sent": sent,
        "received": received,
        "loss_percent": loss,
        "min_ms": minimum,
        "max_ms": maximum,
        "avg_ms": average,
        "success": received > 0,
    }


def run_ping(target: str, count: int = 4, timeout_ms: int = 1000) -> dict[str, Any]:
    target = validate_target(target)
    if os.name == "nt":
        args = ["ping", "-n", str(count), "-w", str(timeout_ms), target]
    else:
        args = ["ping", "-c", str(count), "-W", str(max(1, timeout_ms // 1000)), target]
    output, returncode, duration, timed_out = _run(args, timeout=count * (timeout_ms / 1000 + 0.5) + 3)
    parsed = parse_ping_output(output, expected=count)
    parsed.update(
        {
            "target": target,
            "output": output[:20_000],
            "duration_ms": duration,
            "timed_out": timed_out,
            "return_code": returncode,
        }
    )
    return parsed


def parse_traceroute_output(output: str) -> list[dict[str, Any]]:
    hops: list[dict[str, Any]] = []
    for line in output.splitlines():
        match = re.match(r"^\s*(\d+)\s+(.+)$", line)
        if not match:
            continue
        hop = int(match.group(1))
        remainder = match.group(2)
        if "<1 ms" in remainder.lower() and "*" in remainder and not re.search(r"\d+\.\d+\.\d+\.\d+", remainder):
            continue
        ip_match = re.search(r"(\d{1,3}(?:\.\d{1,3}){3})", remainder)
        times = [float(value) for value in re.findall(r"([\d.]+)\s*ms", remainder)]
        hops.append(
            {
                "hop": hop,
                "ip": ip_match.group(1) if ip_match else None,
                "times_ms": times,
            }
        )
    return hops


def run_traceroute(target: str, max_hops: int = 20) -> dict[str, Any]:
    target = validate_target(target)
    if os.name == "nt":
        args = ["tracert", "-d", "-h", str(max_hops), "-w", "1000", target]
    else:
        args = ["traceroute", "-n", "-m", str(max_hops), "-w", "2", target]
    output, returncode, duration, timed_out = _run(args, timeout=55)
    hops = parse_traceroute_output(output)
    return {
        "target": target,
        "hops": hops,
        "hop_count": len(hops),
        "output": output[:30_000],
        "duration_ms": duration,
        "timed_out": timed_out,
        "return_code": returncode,
        "completed": not timed_out,
    }


def run_dns(target: str, record_type: str = "A") -> dict[str, Any]:
    target = validate_target(target)
    record_type = record_type.upper()
    if record_type not in DNS_TYPES:
        raise ValidationError(f"DNS record type must be one of: {', '.join(sorted(DNS_TYPES))}.")

    resolver = dns.resolver.Resolver(configure=True)
    resolver.timeout = 5
    resolver.lifetime = 5
    started = time.perf_counter()
    result: dict[str, Any] = {
        "target": target,
        "record_type": record_type,
        "records": [],
        "resolved": False,
        "error": None,
        "nameserver": resolver.nameservers[0] if resolver.nameservers else None,
        "duration_ms": 0,
    }
    try:
        answer = resolver.resolve(target, record_type, lifetime=5)
        records: list[str] = []
        for item in answer:
            if record_type == "MX":
                records.append(f"{item.preference} {item.exchange}")
            elif record_type == "TXT":
                records.append("".join(part.decode(errors="replace") for part in item.strings))
            else:
                records.append(item.to_text())
        result["records"] = sorted(set(records))
        result["resolved"] = bool(records)
    except dns.resolver.NXDOMAIN:
        result["error"] = "Domain does not exist (NXDOMAIN)."
    except dns.resolver.NoAnswer:
        result["error"] = f"No {record_type} records found."
    except dns.resolver.NoNameservers:
        result["error"] = "No DNS nameserver responded."
    except dns.exception.Timeout:
        result["error"] = "DNS lookup timed out."
    except dns.exception.DNSException as exc:
        result["error"] = f"DNS error: {exc}"
    result["duration_ms"] = round((time.perf_counter() - started) * 1000, 1)
    return result


def run_connectivity() -> dict[str, Any]:
    started = time.perf_counter()
    targets = connectivity_targets()
    return {
        "targets": targets,
        "online": any(item["online"] for item in targets),
        "duration_ms": round((time.perf_counter() - started) * 1000, 1),
    }
