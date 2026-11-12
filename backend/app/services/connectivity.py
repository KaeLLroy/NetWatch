"""Real internet and public-IP checks (no synthetic results)."""

from __future__ import annotations

import concurrent.futures
import ipaddress
import socket
import time
from typing import Any

import httpx

TCP_TARGETS = (("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53))
NCSI_URL = "http://www.msftconnecttest.com/connecttest.txt"
PUBLIC_IP_ENDPOINTS = (
    ("https://api.ipify.org?format=json", "json"),
    ("https://ifconfig.me/ip", "text"),
    ("https://icanhazip.com", "text"),
)


def _tcp_latency(host: str, port: int, timeout: float = 1.5) -> tuple[float, str] | None:
    started = time.perf_counter()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            latency = (time.perf_counter() - started) * 1000
            return round(latency, 1), f"TCP {host}:{port}"
    except OSError:
        return None


def check_internet() -> dict[str, Any]:
    """Probe reachable TCP endpoints, then the Windows NCSI endpoint as fallback."""
    with concurrent.futures.ThreadPoolExecutor(max_workers=len(TCP_TARGETS)) as pool:
        futures = [pool.submit(_tcp_latency, host, port) for host, port in TCP_TARGETS]
        results = [future.result() for future in futures]
    working = [result for result in results if result]
    if working:
        latency, method = min(working, key=lambda item: item[0])
        return {"online": True, "latency_ms": latency, "method": method}

    started = time.perf_counter()
    try:
        response = httpx.get(NCSI_URL, timeout=3.0, follow_redirects=True)
        if response.status_code == 200 and "Microsoft Connect Test" in response.text:
            return {
                "online": True,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
                "method": "HTTP NCSI",
            }
    except httpx.HTTPError:
        pass
    return {"online": False, "latency_ms": None, "method": None}


def _is_public_ip(value: str) -> bool:
    try:
        address = ipaddress.ip_address(value.strip())
    except ValueError:
        return False
    return not (
        address.is_private
        or address.is_loopback
        or address.is_link_local
        or address.is_multicast
        or address.is_reserved
        or address.is_unspecified
    )


def get_public_ip() -> str | None:
    """Resolve the public egress IP through independent HTTPS providers."""
    headers = {"User-Agent": "NetWatch/1.0 (local network monitor)"}
    for url, kind in PUBLIC_IP_ENDPOINTS:
        try:
            response = httpx.get(url, timeout=4.0, headers=headers, follow_redirects=True)
            if response.status_code != 200:
                continue
            value = (
                response.json().get("ip", "") if kind == "json" else response.text.strip()
            )
            if _is_public_ip(value):
                return value.strip()
        except (httpx.HTTPError, ValueError):
            continue
    return None


def connectivity_targets() -> list[dict[str, Any]]:
    """Detailed target status for the diagnostics page."""
    targets: list[dict[str, Any]] = []
    for host, port in TCP_TARGETS:
        target = _tcp_latency(host, port)
        targets.append(
            {
                "name": f"TCP {host}:{port}",
                "online": target is not None,
                "latency_ms": target[0] if target else None,
            }
        )
    try:
        started = time.perf_counter()
        socket.getaddrinfo("www.microsoft.com", 443, type=socket.SOCK_STREAM)
        targets.append(
            {
                "name": "DNS resolution",
                "online": True,
                "latency_ms": round((time.perf_counter() - started) * 1000, 1),
            }
        )
    except OSError:
        targets.append({"name": "DNS resolution", "online": False, "latency_ms": None})
    return targets
