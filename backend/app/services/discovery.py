"""Safe local-network device discovery without packet capture.

The scan combines ICMP echo requests with the Windows neighbor (ARP) cache.
No payloads are captured, no ports are probed, and targets are restricted to
the private subnet of the selected local adapter.
"""

from __future__ import annotations

import concurrent.futures
import os
import re
import socket
import subprocess
import threading
import time
from typing import Any

import psutil
from flask import Flask

from ..config import ValidationError
from ..db import Database
from .interfaces import local_network, normalize_mac, resolve_primary_interface

ARP_PATTERN = re.compile(
    r"(\d{1,3}(?:\.\d{1,3}){3})\s+([0-9a-fA-F]{2}(?:[-:][0-9a-fA-F]{2}){5})"
)
CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


def _ping(ip: str, timeout_ms: int) -> bool:
    if os.name == "nt":
        args = ["ping", "-n", "1", "-w", str(timeout_ms), ip]
    else:
        args = ["ping", "-c", "1", "-W", str(max(1, timeout_ms // 1000)), ip]
    kwargs: dict[str, Any] = {"capture_output": True, "timeout": timeout_ms / 1000 + 2}
    if os.name == "nt":
        kwargs["creationflags"] = CREATE_NO_WINDOW
    try:
        return subprocess.run(args, **kwargs).returncode == 0  # noqa: S603
    except (subprocess.TimeoutExpired, OSError):
        return False


def read_arp_table() -> dict[str, str]:
    """Return IP -> MAC entries from the Windows neighbor cache."""
    if os.name != "nt":
        return {}
    try:
        completed = subprocess.run(
            ["arp", "-a"],
            capture_output=True,
            timeout=10,
            creationflags=CREATE_NO_WINDOW,
        )
    except (subprocess.TimeoutExpired, OSError):
        return {}
    text = completed.stdout.decode("utf-8", errors="replace")
    entries: dict[str, str] = {}
    for ip, mac in ARP_PATTERN.findall(text):
        normalized = normalize_mac(mac)
        if normalized:
            entries[ip] = normalized
    return entries


def _hostname(ip: str) -> str | None:
    try:
        return socket.gethostbyaddr(ip)[0]
    except (OSError, socket.herror):
        return None


class DiscoveryService:
    """Coordinate one background discovery scan at a time."""

    def __init__(self, app: Flask, socketio: Any, database: Database) -> None:
        self.app = app
        self.socketio = socketio
        self.database = database
        self._lock = threading.Lock()
        self._state: dict[str, Any] = {
            "running": False,
            "phase": "idle",
            "progress": 0,
            "total": 0,
            "percent": 0,
            "interface": None,
            "network": None,
            "started_at": None,
            "finished_at": None,
            "result": None,
            "error": None,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            return dict(self._state)

    def start(self, confirm: bool) -> dict[str, Any]:
        if confirm is not True:
            raise ValidationError("Discovery requires explicit confirmation that the network is authorized.")
        with self._lock:
            if self._state["running"]:
                return dict(self._state)

        settings = self.database.get_settings()
        interface = resolve_primary_interface(str(settings.get("interface", "")))
        if not interface:
            raise ValidationError("No active network interface is available for discovery.")
        network = local_network(interface)
        if network is None:
            raise ValidationError(
                "The selected interface has no private IPv4 subnet suitable for safe discovery."
            )

        with self._lock:
            self._state = {
                "running": True,
                "phase": "scanning",
                "progress": 0,
                "total": max(0, network.num_addresses - 2),
                "percent": 0,
                "interface": interface,
                "network": str(network),
                "started_at": int(time.time()),
                "finished_at": None,
                "result": None,
                "error": None,
            }
        threading.Thread(
            target=self._run, args=(network, interface), name="netwatch-discovery", daemon=True
        ).start()
        return self.status()

    def _update(self, **values: Any) -> None:
        with self._lock:
            self._state.update(values)
            total = self._state["total"] or 1
            self._state["percent"] = min(100, round(self._state["progress"] * 100 / total))

    def _run(self, network: Any, interface: str) -> None:
        try:
            settings = self.database.get_settings()
            timeout_ms = int(settings.get("discovery_timeout_ms", 400))
            own_ip = None
            for entry in psutil.net_if_addrs().get(interface, []):
                if entry.family == socket.AF_INET:
                    own_ip = entry.address
                    break

            hosts = [str(host) for host in network.hosts() if str(host) != own_ip]
            network_hosts = set(hosts)
            self._update(total=len(hosts), progress=0)
            responded: set[str] = set()
            completed = 0
            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
                futures = {pool.submit(_ping, ip, timeout_ms): ip for ip in hosts}
                for future in concurrent.futures.as_completed(futures):
                    if future.result():
                        responded.add(futures[future])
                    completed += 1
                    if completed % 4 == 0 or completed == len(hosts):
                        self._update(progress=completed, phase="scanning")

            self._update(phase="resolving", progress=completed)
            arp = read_arp_table()
            discovered_ips = set(responded)
            for ip in arp:
                if ip in network_hosts:
                    discovered_ips.add(ip)

            hostnames: dict[str, str] = {}
            if discovered_ips:
                with concurrent.futures.ThreadPoolExecutor(max_workers=8) as pool:
                    futures = {pool.submit(_hostname, ip): ip for ip in discovered_ips}
                    try:
                        for future in concurrent.futures.as_completed(futures, timeout=8):
                            name = future.result()
                            if name:
                                hostnames[futures[future]] = name
                    except concurrent.futures.TimeoutError:
                        pass

            findings = [
                {"ip": ip, "mac": arp.get(ip), "hostname": hostnames.get(ip, "")}
                for ip in sorted(discovered_ips, key=lambda value: tuple(int(p) for p in value.split(".")))
            ]
            self._update(phase="saving")
            result = self.database.scan_devices(interface, findings, int(time.time()))
            result.update(
                {
                    "interface": interface,
                    "network": str(network),
                    "responded": len(responded),
                    "scan_duration_ms": round(
                        (time.time() - (self._state["started_at"] or time.time())) * 1000
                    ),
                }
            )
            self._update(
                running=False,
                phase="done",
                progress=len(hosts),
                percent=100,
                finished_at=int(time.time()),
                result=result,
            )
            if self.socketio is not None:
                with self.app.app_context():
                    self.socketio.emit("devices_updated", result)
        except Exception as exc:  # noqa: BLE001 - report failures to the UI
            self.app.logger.exception("Device discovery failed")
            self._update(
                running=False,
                phase="error",
                finished_at=int(time.time()),
                error=str(exc),
            )
