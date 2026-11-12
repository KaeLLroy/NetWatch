"""Background network sampling, connectivity checks, and alert detection."""

from __future__ import annotations

import threading
import time
from typing import Any

import psutil
from flask import Flask

from .db import Database
from .metrics import RateSample, compute_rate, counter_delta_is_plausible
from .services.alerts import AlertService
from .services.connectivity import check_internet, get_public_ip
from .services.interfaces import (
    get_interface,
    local_ip,
    resolve_primary_interface,
    system_info,
)

TELEMETRY_EVENT = "telemetry"


class NetworkMonitor(threading.Thread):
    """Continuously samples real adapter counters and internet reachability."""

    def __init__(
        self,
        app: Flask,
        socketio: Any,
        database: Database,
        alerts: AlertService,
    ) -> None:
        super().__init__(name="netwatch-monitor", daemon=True)
        self.app = app
        self.socketio = socketio
        self.database = database
        self.alerts = alerts
        self._lock = threading.RLock()
        self._wake = threading.Event()
        self._stop = threading.Event()
        self._settings = database.get_settings()
        self._previous: dict[str, tuple[int, float, int, int, int, int]] = {}
        self._latest: dict[str, Any] = self._empty_snapshot()
        self._internet_online: bool | None = None
        self._internet_latency: float | None = None
        self._internet_method: str | None = None
        self._public_ip: str | None = None
        self._public_ip_checked_at: int | None = None
        self._public_fetching = False
        self._last_connectivity_check = 0.0
        self._last_cleanup = time.time()
        self._above_threshold = {"download": False, "upload": False}
        self._interface_healthy = True
        self._running = False
        self._last_error: str | None = None

    # ------------------------------------------------------------------ lifecycle
    def _empty_snapshot(self) -> dict[str, Any]:
        info = system_info()
        selected = self._settings.get("interface", "") if hasattr(self, "_settings") else ""
        return {
            "timestamp": int(time.time()),
            "interface": selected or None,
            "interface_status": "starting",
            "local_ip": None,
            "mac": None,
            "link_speed_mbps": None,
            "download_bps": 0.0,
            "upload_bps": 0.0,
            "bytes_sent_delta": 0,
            "bytes_recv_delta": 0,
            "total_bytes_sent": 0,
            "total_bytes_recv": 0,
            "internet_online": None,
            "internet_latency_ms": None,
            "internet_method": None,
            "public_ip": None,
            "public_ip_checked_at": None,
            "system_uptime_seconds": info["uptime_seconds"],
            "hostname": info["hostname"],
            "platform": info["platform"],
            "monitor_running": False,
            "last_error": None,
        }

    def run(self) -> None:  # pragma: no cover - exercised in integration runs
        self._running = True
        self.app.logger.info("Network monitor started")
        try:
            self.sample_once()
            self._check_connectivity()
            while not self._stop.is_set():
                interval = max(1, int(self._settings.get("refresh_interval", 2)))
                self._wake.wait(timeout=interval)
                self._wake.clear()
                if self._stop.is_set():
                    break
                try:
                    self.sample_once()
                    now = time.time()
                    check_interval = int(self._settings.get("internet_check_interval", 15))
                    if now - self._last_connectivity_check >= check_interval:
                        self._check_connectivity()
                    if now - self._last_cleanup >= 3600:
                        self._cleanup()
                except Exception as exc:  # noqa: BLE001 - monitoring must survive
                    self._last_error = str(exc)
                    self.app.logger.exception("Monitoring cycle failed")
                    self._set_latest(last_error=self._last_error, monitor_running=True)
        finally:
            self._running = False
            self.app.logger.info("Network monitor stopped")

    def stop(self) -> None:
        self._stop.set()
        self._wake.set()

    # ------------------------------------------------------------------- settings
    def reload_settings(self) -> dict[str, Any]:
        new_settings = self.database.get_settings()
        with self._lock:
            interface_changed = new_settings.get("interface") != self._settings.get("interface")
            self._settings = new_settings
            if interface_changed:
                self._previous.clear()
                self._interface_healthy = True
                self._above_threshold = {"download": False, "upload": False}
        self._wake.set()
        return new_settings

    def _cleanup(self) -> None:
        retention = int(self._settings.get("retention_days", 30))
        result = self.database.cleanup(retention)
        self._last_cleanup = time.time()
        self.app.logger.info("Retention cleanup removed %s", result)

    # -------------------------------------------------------------------- sampling
    def sample_once(self) -> dict[str, Any]:
        settings = dict(self._settings)
        selected = str(settings.get("interface", ""))
        primary = resolve_primary_interface(selected)
        interface = primary or (selected or None)
        stats = psutil.net_if_stats()
        counters = psutil.net_io_counters(pernic=True)
        state = stats.get(interface) if interface else None
        io = counters.get(interface) if interface else None
        available = bool(interface and state and state.isup and io)

        if not available:
            if self._interface_healthy:
                self._interface_healthy = False
                message = (
                    f"Selected interface '{interface}' is unavailable."
                    if selected and interface
                    else "No active network interface detected."
                )
                self.alerts.trigger(
                    "interface_down", "critical", message, dedupe_seconds=0
                )
            self._set_latest(
                timestamp=int(time.time()),
                interface=interface,
                interface_status="unavailable",
                local_ip=None,
                mac=None,
                link_speed_mbps=None,
                download_bps=0.0,
                upload_bps=0.0,
                bytes_sent_delta=0,
                bytes_recv_delta=0,
                monitor_running=True,
                last_error=None,
            )
            self._emit_telemetry()
            return self.snapshot()

        if not self._interface_healthy:
            self._interface_healthy = True
            self.alerts.trigger(
                "interface_restored",
                "info",
                f"Interface '{interface}' is available again.",
                dedupe_seconds=0,
            )

        now = int(time.time())
        monotonic = time.monotonic()
        previous = self._previous.get(interface)
        elapsed = (monotonic - previous[1]) if previous else 0.0
        rate = compute_rate(
            previous[2] if previous else io.bytes_sent,
            previous[3] if previous else io.bytes_recv,
            io.bytes_sent,
            io.bytes_recv,
            elapsed,
        )
        self._previous[interface] = (
            now,
            monotonic,
            int(io.bytes_sent),
            int(io.bytes_recv),
            int(io.packets_sent),
            int(io.packets_recv),
        )

        if previous is not None:
            sent_packets = int(io.packets_sent) - previous[4]
            recv_packets = int(io.packets_recv) - previous[5]
            sent_ok = counter_delta_is_plausible(
                rate.bytes_sent,
                sent_packets,
                elapsed_seconds=elapsed,
                link_speed_mbps=state.speed,
            )
            recv_ok = counter_delta_is_plausible(
                rate.bytes_recv,
                recv_packets,
                elapsed_seconds=elapsed,
                link_speed_mbps=state.speed,
            )
            if not (sent_ok and recv_ok):
                self.app.logger.warning(
                    "Ignored implausible adapter counter delta on %s "
                    "(sent=%d B/%d pkt, recv=%d B/%d pkt in %.2fs)",
                    interface,
                    rate.bytes_sent,
                    sent_packets,
                    rate.bytes_recv,
                    recv_packets,
                    elapsed,
                )
                rate = RateSample(
                    bytes_sent=rate.bytes_sent if sent_ok else 0,
                    bytes_recv=rate.bytes_recv if recv_ok else 0,
                    upload_bps=rate.upload_bps if sent_ok else 0.0,
                    download_bps=rate.download_bps if recv_ok else 0.0,
                )
            try:
                self.database.insert_sample(
                    now,
                    interface,
                    rate.bytes_sent,
                    rate.bytes_recv,
                    rate.upload_bps,
                    rate.download_bps,
                )
            except Exception:  # noqa: BLE001 - persistence failure must not stop sampling
                self.app.logger.exception("Unable to persist traffic sample")
            self._check_thresholds(rate.download_bps, rate.upload_bps)

        detail = get_interface(interface)
        self._set_latest(
            timestamp=now,
            interface=interface,
            interface_status="up",
            local_ip=local_ip(interface),
            mac=detail.get("mac") if detail else None,
            link_speed_mbps=state.speed or None,
            download_bps=rate.download_bps,
            upload_bps=rate.upload_bps,
            bytes_sent_delta=rate.bytes_sent,
            bytes_recv_delta=rate.bytes_recv,
            total_bytes_sent=int(io.bytes_sent),
            total_bytes_recv=int(io.bytes_recv),
            internet_online=self._internet_online,
            internet_latency_ms=self._internet_latency,
            internet_method=self._internet_method,
            public_ip=self._public_ip,
            public_ip_checked_at=self._public_ip_checked_at,
            system_uptime_seconds=system_info()["uptime_seconds"],
            monitor_running=True,
            last_error=None,
        )
        self._emit_telemetry()
        return self.snapshot()

    # ------------------------------------------------------------------ thresholds
    def _check_thresholds(self, download_bps: float, upload_bps: float) -> None:
        settings = self._settings
        checks = (
            ("download", download_bps, float(settings.get("download_threshold_mbps", 0))),
            ("upload", upload_bps, float(settings.get("upload_threshold_mbps", 0))),
        )
        for direction, bps, threshold_mbps in checks:
            if threshold_mbps <= 0:
                continue
            mbps = bps / 1_000_000
            if mbps >= threshold_mbps and not self._above_threshold[direction]:
                self._above_threshold[direction] = True
                label = "Download" if direction == "download" else "Upload"
                self.alerts.trigger(
                    f"{direction}_threshold",
                    "warning",
                    f"{label} speed {mbps:.1f} Mbps exceeded the {threshold_mbps:.1f} Mbps threshold.",
                )
            elif mbps < threshold_mbps * 0.8:
                self._above_threshold[direction] = False

    # ---------------------------------------------------------------- connectivity
    def _check_connectivity(self) -> dict[str, Any]:
        result = check_internet()
        now = int(time.time())
        previous = self._internet_online
        self._internet_online = bool(result["online"])
        self._internet_latency = result["latency_ms"]
        self._internet_method = result["method"]
        self._last_connectivity_check = time.time()

        try:
            self.database.record_connectivity(
                now, self._internet_online, self._internet_latency, self._internet_method
            )
        except Exception:  # noqa: BLE001
            self.app.logger.exception("Unable to persist connectivity check")

        if not self._internet_online:
            if previous is None or previous is True:
                self.alerts.trigger(
                    "internet_down",
                    "critical",
                    "Internet connectivity was lost.",
                    dedupe_seconds=0,
                )
        elif previous is False:
            self.alerts.trigger(
                "internet_restored",
                "info",
                "Internet connectivity was restored.",
                dedupe_seconds=0,
            )

        self._set_latest(
            internet_online=self._internet_online,
            internet_latency_ms=self._internet_latency,
            internet_method=self._internet_method,
            public_ip=self._public_ip,
            public_ip_checked_at=self._public_ip_checked_at,
        )
        self._emit(
            "connectivity",
            {
                "online": self._internet_online,
                "latency_ms": self._internet_latency,
                "method": self._internet_method,
                "public_ip": self._public_ip,
                "checked_at": now,
            },
        )

        if self._internet_online:
            self._maybe_fetch_public_ip(force=previous is False)
        return result

    def _maybe_fetch_public_ip(self, force: bool = False) -> None:
        settings = self._settings
        if not settings.get("public_ip_enabled", True):
            return
        stale = (
            self._public_ip_checked_at is None
            or time.time() - self._public_ip_checked_at > 600
        )
        if not (force or stale) or self._public_fetching:
            return
        with self._lock:
            if self._public_fetching:
                return
            self._public_fetching = True

        def worker() -> None:
            try:
                address = get_public_ip()
                now = int(time.time())
                with self._lock:
                    self._public_ip = address
                    self._public_ip_checked_at = now
                self._set_latest(public_ip=address, public_ip_checked_at=now)
                self._emit(
                    "connectivity",
                    {
                        "online": self._internet_online,
                        "latency_ms": self._internet_latency,
                        "method": self._internet_method,
                        "public_ip": address,
                        "checked_at": now,
                    },
                )
            except Exception:  # noqa: BLE001
                self.app.logger.exception("Public IP lookup failed")
            finally:
                with self._lock:
                    self._public_fetching = False

        threading.Thread(target=worker, name="netwatch-public-ip", daemon=True).start()

    # ---------------------------------------------------------------------- helpers
    def _set_latest(self, **values: Any) -> None:
        with self._lock:
            self._latest.update(values)

    def _emit_telemetry(self) -> None:
        snapshot = self.snapshot()
        self._emit(
            TELEMETRY_EVENT,
            {
                key: snapshot[key]
                for key in (
                    "timestamp",
                    "interface",
                    "interface_status",
                    "local_ip",
                    "download_bps",
                    "upload_bps",
                    "bytes_sent_delta",
                    "bytes_recv_delta",
                    "total_bytes_sent",
                    "total_bytes_recv",
                    "internet_online",
                    "internet_latency_ms",
                    "public_ip",
                    "system_uptime_seconds",
                )
            },
        )

    def _emit(self, event: str, payload: dict[str, Any]) -> None:
        if self.socketio is None:
            return
        try:
            with self.app.app_context():
                self.socketio.emit(event, payload)
        except Exception:  # noqa: BLE001
            self.app.logger.exception("Unable to emit %s", event)

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            snapshot = dict(self._latest)
        snapshot["system_uptime_seconds"] = system_info()["uptime_seconds"]
        snapshot["monitor_running"] = bool(self._running or self.is_alive())
        return snapshot
