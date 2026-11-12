"""Active TCP connection inventory with Windows permission handling."""

from __future__ import annotations

import socket
from typing import Any

import psutil


def _format_address(address: Any) -> str | None:
    if not address:
        return None
    ip = getattr(address, "ip", None)
    port = getattr(address, "port", None)
    if not ip:
        return None
    if ":" in ip:
        return f"[{ip}]:{port}" if port is not None else f"[{ip}]"
    return f"{ip}:{port}" if port is not None else ip


def list_tcp_connections(state_filter: str | None = None) -> dict[str, Any]:
    """Return TCP connections and best-effort process attribution."""
    try:
        connections = psutil.net_connections(kind="tcp")
        restricted = False
        message = None
    except psutil.AccessDenied:
        return {
            "connections": [],
            "counts": {},
            "total": 0,
            "restricted": True,
            "message": "Windows denied access to the connection table. Run NetWatch elevated for full visibility.",
            "timestamp": None,
        }

    process_cache: dict[int, str] = {}
    items: list[dict[str, Any]] = []
    counts: dict[str, int] = {}

    for connection in connections:
        state = connection.status or "UNKNOWN"
        counts[state] = counts.get(state, 0) + 1
        if state_filter and state_filter != "all" and state != state_filter:
            continue

        process_name = None
        pid = connection.pid
        if pid:
            if pid not in process_cache:
                try:
                    process_cache[pid] = psutil.Process(pid).name()
                except psutil.AccessDenied:
                    process_cache[pid] = "Access denied"
                except (psutil.NoSuchProcess, psutil.ZombieProcess):
                    process_cache[pid] = "Exited"
            process_name = process_cache[pid]
        elif pid == 0:
            process_name = "System"
            pid = None

        items.append(
            {
                "local": _format_address(connection.laddr),
                "remote": _format_address(connection.raddr),
                "state": state,
                "pid": pid,
                "process": process_name,
                "family": "IPv6" if connection.family == socket.AF_INET6 else "IPv4",
            }
        )

    order = {"ESTABLISHED": 0, "LISTEN": 1, "SYN_SENT": 2, "TIME_WAIT": 3}
    items.sort(key=lambda item: (order.get(item["state"], 9), item["remote"] or "", item["local"] or ""))
    return {
        "connections": items,
        "counts": counts,
        "total": len(items),
        "restricted": restricted,
        "message": message,
        "timestamp": None,
    }
