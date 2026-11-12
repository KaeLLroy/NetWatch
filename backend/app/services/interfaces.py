"""Network adapter discovery and metadata."""

from __future__ import annotations

import ipaddress
import platform
import socket
import time
from typing import Any

import psutil

AF_LINK = getattr(psutil, "AF_LINK", object())


def normalize_mac(address: str | None) -> str | None:
    """Normalize Windows, Linux, and Cisco MAC formats to AA:BB:CC:DD:EE:FF."""
    if not address:
        return None
    cleaned = address.replace("-", ":").strip().upper()
    if "." in cleaned:
        compact = cleaned.replace(".", "").replace(":", "")
        if len(compact) != 12:
            return None
        cleaned = ":".join(compact[index : index + 2] for index in range(0, 12, 2))
    if cleaned in {"00:00:00:00:00:00", ""}:
        return None
    parts = cleaned.split(":")
    if len(parts) != 6 or any(len(part) != 2 for part in parts):
        return None
    try:
        int("".join(parts), 16)
    except ValueError:
        return None
    return cleaned


def _classify(name: str, ipv4: str | None) -> str:
    lower = name.lower()
    if "loopback" in lower or (ipv4 and ipv4.startswith("127.")):
        return "loopback"
    if any(token in lower for token in ("wi-fi", "wifi", "wireless", "wlan")):
        return "wifi"
    if any(token in lower for token in ("vpn", "tap", "tun", "wireguard", "zerotier")):
        return "vpn"
    if any(token in lower for token in ("virtual", "vmware", "hyper-v", "vethernet", "host-only")):
        return "virtual"
    return "ethernet"


def _default_route_ip() -> str | None:
    """Find the local address Windows would use for outbound traffic."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except OSError:
        return None
    finally:
        sock.close()


def resolve_primary_interface(selected: str = "") -> str | None:
    """Return the explicitly selected adapter, or the best automatic candidate."""
    stats = psutil.net_if_stats()
    if selected:
        return selected if selected in stats else None

    addrs = psutil.net_if_addrs()
    io = psutil.net_io_counters(pernic=True)
    route_ip = _default_route_ip()

    if route_ip:
        for name, entries in addrs.items():
            if any(
                entry.family == socket.AF_INET and entry.address == route_ip
                for entry in entries
            ) and stats.get(name) and stats[name].isup:
                return name

    candidates: list[tuple[int, str]] = []
    for name, entries in addrs.items():
        state = stats.get(name)
        if not state or not state.isup:
            continue
        ipv4 = next((entry.address for entry in entries if entry.family == socket.AF_INET), None)
        if not ipv4 or ipv4.startswith("169.254."):
            continue
        lower = name.lower()
        if "loopback" in lower or ipv4.startswith("127."):
            continue
        counters = io.get(name)
        score = counters.bytes_sent + counters.bytes_recv if counters else 0
        candidates.append((score, name))
    return max(candidates)[1] if candidates else None


def _address_lists(entries: list[Any]) -> tuple[list[str], list[str], str | None]:
    ipv4: list[str] = []
    ipv6: list[str] = []
    mac: str | None = None
    for entry in entries:
        if entry.family == socket.AF_INET:
            ipv4.append(entry.address)
        elif entry.family == socket.AF_INET6:
            ipv6.append(entry.address)
        elif entry.family == AF_LINK:
            mac = normalize_mac(entry.address) or mac
    return ipv4, ipv6, mac


def get_interfaces(selected_setting: str = "") -> dict[str, Any]:
    """Return every adapter with addresses, counters, and selection state."""
    stats = psutil.net_if_stats()
    addrs = psutil.net_if_addrs()
    counters = psutil.net_io_counters(pernic=True)
    primary = resolve_primary_interface(selected_setting)
    interfaces: list[dict[str, Any]] = []

    for name in sorted(addrs, key=str.lower):
        ipv4_addresses, ipv6_addresses, mac = _address_lists(addrs[name])
        ipv4 = ipv4_addresses[0] if ipv4_addresses else None
        state = stats.get(name)
        io = counters.get(name)
        interfaces.append(
            {
                "name": name,
                "type": _classify(name, ipv4),
                "is_up": bool(state.isup) if state else False,
                "link_speed_mbps": int(state.speed) if state else 0,
                "mtu": int(state.mtu) if state else 0,
                "duplex": getattr(state.duplex, "name", str(state.duplex)) if state else "unknown",
                "ipv4": ipv4,
                "ipv4_addresses": ipv4_addresses,
                "ipv6": ipv6_addresses[0] if ipv6_addresses else None,
                "ipv6_addresses": ipv6_addresses,
                "mac": mac,
                "is_primary": name == primary,
                "is_selected": name == (selected_setting or primary),
                "bytes_sent": int(io.bytes_sent) if io else 0,
                "bytes_recv": int(io.bytes_recv) if io else 0,
                "packets_sent": int(io.packets_sent) if io else 0,
                "packets_recv": int(io.packets_recv) if io else 0,
                "errors_in": int(io.errin) if io else 0,
                "errors_out": int(io.errout) if io else 0,
                "drops_in": int(io.dropin) if io else 0,
                "drops_out": int(io.dropout) if io else 0,
            }
        )

    return {
        "interfaces": interfaces,
        "selected": selected_setting,
        "primary": primary,
        "count": len(interfaces),
        "up_count": sum(1 for item in interfaces if item["is_up"]),
    }


def get_interface(name: str) -> dict[str, Any] | None:
    for item in get_interfaces()["interfaces"]:
        if item["name"] == name:
            return item
    return None


def local_ip(name: str | None) -> str | None:
    if not name:
        return None
    for entry in psutil.net_if_addrs().get(name, []):
        if entry.family == socket.AF_INET and not entry.address.startswith("169.254."):
            return entry.address
    return None


def local_network(name: str | None) -> ipaddress.IPv4Network | None:
    """Return a safe, private /24-or-smaller network for discovery."""
    if not name:
        return None
    entries = psutil.net_if_addrs().get(name, [])
    for entry in entries:
        if entry.family != socket.AF_INET or not entry.netmask:
            continue
        try:
            iface = ipaddress.ip_interface(f"{entry.address}/{entry.netmask}")
        except ValueError:
            continue
        network = iface.network
        if iface.ip.is_loopback or iface.ip.is_link_local:
            return None
        if network.prefixlen < 24:
            network = ipaddress.ip_network(f"{iface.ip}/24", strict=False)
        if not network.is_private:
            return None
        if network.num_addresses > 256:
            return None
        return network
    return None


def system_info() -> dict[str, Any]:
    boot_time = psutil.boot_time()
    return {
        "hostname": platform.node(),
        "platform": platform.platform(),
        "python_version": platform.python_version(),
        "boot_time": int(boot_time),
        "uptime_seconds": max(0, int(time.time() - boot_time)),
        "cpu_count": psutil.cpu_count(logical=True),
        "memory_total": psutil.virtual_memory().total,
    }
