"""JSON API routes for NetWatch."""

from __future__ import annotations

import csv
import io
import time
from datetime import date, datetime, timedelta
from datetime import time as datetime_time
from typing import Any

import psutil
from flask import Blueprint, Response, current_app, jsonify, request
from werkzeug.exceptions import HTTPException

from ..config import APP_VERSION, DEFAULT_SETTINGS, ValidationError, validate_settings_payload
from ..db import Database
from ..monitoring import NetworkMonitor
from ..services.alerts import AlertService
from ..services.connections import list_tcp_connections
from ..services.diagnostics import run_connectivity, run_dns, run_ping, run_traceroute
from ..services.discovery import DiscoveryService
from ..services.interfaces import (
    get_interfaces,
    local_network,
    resolve_primary_interface,
    system_info,
)

api = Blueprint("api", __name__, url_prefix="/api")

TRAFFIC_RANGES = {
    "1h": (3600, 30),
    "6h": (21600, 120),
    "24h": (86400, 300),
    "7d": (604800, 1800),
    "30d": (2592000, 7200),
}
_state: dict[str, float] = {}


class ApiError(Exception):
    def __init__(self, message: str, status: int = 400) -> None:
        super().__init__(message)
        self.message = message
        self.status = status


def ok(data: Any = None, status: int = 200):
    return jsonify({"ok": True, "data": data}), status


def fail(message: str, status: int = 400, code: str | None = None):
    body: dict[str, Any] = {"ok": False, "error": message}
    if code:
        body["code"] = code
    return jsonify(body), status


def db() -> Database:
    return current_app.extensions["db"]


def monitor() -> NetworkMonitor:
    return current_app.extensions["monitor"]


def discovery() -> DiscoveryService:
    return current_app.extensions["discovery"]


def alerts() -> AlertService:
    return current_app.extensions["alerts"]


def _broadcast(event: str, payload: Any) -> None:
    socketio = current_app.extensions.get("socketio")
    if socketio is None:
        return
    try:
        socketio.emit(event, payload)
    except Exception:  # noqa: BLE001 - realtime delivery is best effort
        current_app.logger.exception("Unable to broadcast %s", event)


def _rate_limit(name: str, seconds: float) -> None:
    remote = request.remote_addr or "local"
    key = f"{name}:{remote}"
    now = time.monotonic()
    if now - _state.get(key, 0) < seconds:
        raise ApiError("Please wait before running that diagnostic again.", 429)
    _state[key] = now


def _int_arg(name: str, default: int, minimum: int, maximum: int) -> int:
    raw = request.args.get(name, str(default))
    try:
        value = int(raw)
    except (TypeError, ValueError) as exc:
        raise ApiError(f"{name} must be an integer.") from exc
    if not minimum <= value <= maximum:
        raise ApiError(f"{name} must be between {minimum} and {maximum}.")
    return value


def _selected_interface(settings: dict[str, Any] | None = None) -> str:
    settings = settings or db().get_settings()
    snapshot = monitor().snapshot()
    return str(snapshot.get("interface") or settings.get("interface") or "")


def _interface_arg(default: str) -> str:
    value = request.args.get("interface", default).strip()
    if len(value) > 128 or any(ord(char) < 32 for char in value):
        raise ApiError("interface is invalid.")
    return value or default


def _json_body() -> dict[str, Any]:
    payload = request.get_json(silent=True)
    if payload is None:
        return {}
    if not isinstance(payload, dict):
        raise ApiError("Request body must be a JSON object.")
    return payload


@api.before_request
def enforce_local_json():
    """Reject cross-site state changes and non-JSON mutation bodies."""
    if request.method not in {"POST", "PUT", "PATCH", "DELETE"}:
        return None
    fetch_site = request.headers.get("Sec-Fetch-Site")
    if fetch_site and fetch_site not in {"same-origin", "same-site", "none"}:
        return fail("Cross-site requests are not allowed.", 403)
    origin = request.headers.get("Origin")
    if origin:
        from urllib.parse import urlparse

        if urlparse(origin).netloc != request.host:
            return fail("Cross-origin requests are not allowed.", 403)
    if not request.is_json:
        return fail("Content-Type must be application/json.", 415)
    return None


@api.errorhandler(ApiError)
def handle_api_error(error: ApiError):
    return fail(error.message, error.status)


@api.errorhandler(ValidationError)
def handle_validation_error(error: ValidationError):
    return fail(str(error), 400)


@api.errorhandler(RuntimeError)
def handle_runtime_error(error: RuntimeError):
    current_app.logger.error("Diagnostic tool error: %s", error)
    return fail(str(error), 503)


@api.errorhandler(HTTPException)
def handle_http_error(error: HTTPException):
    return fail(error.description or "Request failed.", error.code or 400)


@api.errorhandler(Exception)
def handle_unexpected_error(error: Exception):
    current_app.logger.exception("Unhandled API error", exc_info=error)
    return fail("Internal server error.", 500)


# ----------------------------------------------------------------------- system
@api.get("/health")
def health():
    db().ping()
    return ok(
        {
            "status": "ok",
            "version": APP_VERSION,
            "monitor_running": monitor().snapshot()["monitor_running"],
            "database": str(current_app.config["DATABASE"]),
        }
    )


@api.get("/system/info")
def system_status():
    process = psutil.Process()
    snapshot = monitor().snapshot()
    settings = db().get_settings()
    return ok(
        {
            "version": APP_VERSION,
            "python": system_info()["python_version"],
            "platform": system_info()["platform"],
            "hostname": system_info()["hostname"],
            "data_dir": str(current_app.config["DATABASE"].parent),
            "log_file": str(current_app.config["LOG_FILE"]),
            "database_size": db().database_size(),
            "process_started": int(process.create_time()),
            "monitor_running": snapshot["monitor_running"],
            "monitor_error": snapshot.get("last_error"),
            "settings": settings,
            "interfaces": get_interfaces(settings["interface"])["count"],
        }
    )


# ---------------------------------------------------------------------- dashboard
@api.get("/dashboard/summary")
def dashboard_summary():
    settings = db().get_settings()
    snapshot = monitor().snapshot()
    interface_data = get_interfaces(settings["interface"])
    iface = snapshot.get("interface") or interface_data["primary"]
    today = db().today_totals(iface) if iface else db().today_totals()
    lifetime = db().lifetime_totals()
    return ok(
        {
            "monitor": snapshot,
            "today": today,
            "lifetime": lifetime,
            "interface": interface_data,
            "settings": {
                key: settings[key]
                for key in (
                    "refresh_interval",
                    "interface",
                    "chart_points",
                    "notifications_enabled",
                    "public_ip_enabled",
                    "compact_mode",
                )
            },
            "unread_alerts": db().unread_alert_count(),
            "system": system_info(),
            "database_size": db().database_size(),
        }
    )


# --------------------------------------------------------------------- interfaces
@api.get("/interfaces")
def interfaces():
    settings = db().get_settings()
    data = get_interfaces(settings["interface"])
    data["selected_setting"] = settings["interface"]
    return ok(data)


@api.post("/interfaces/select")
def select_interface():
    payload = _json_body()
    cleaned = validate_settings_payload({"interface": payload.get("interface", "")})
    if cleaned["interface"]:
        names = {item["name"] for item in get_interfaces()["interfaces"]}
        if cleaned["interface"] not in names:
            raise ApiError("The selected interface does not exist on this machine.")
    settings = db().save_settings(cleaned)
    monitor().reload_settings()
    _broadcast("settings_updated", settings)
    data = get_interfaces(settings["interface"])
    data["selected_setting"] = settings["interface"]
    return ok(data)


# ------------------------------------------------------------------------ traffic
@api.get("/traffic/history")
def traffic_history():
    range_key = request.args.get("range", "24h")
    if range_key not in TRAFFIC_RANGES:
        raise ApiError(f"range must be one of: {', '.join(TRAFFIC_RANGES)}.")
    seconds, bucket = TRAFFIC_RANGES[range_key]
    iface = _interface_arg(_selected_interface())
    if not iface:
        return ok({"range": range_key, "interface": "", "points": [], "summary": {}})
    since = int(time.time()) - seconds
    points = db().traffic_history(iface, since, bucket)
    return ok(
        {
            "range": range_key,
            "interface": iface,
            "bucket_seconds": bucket,
            "points": points,
            "summary": {
                "bytes_sent": sum(int(point["bytes_sent"] or 0) for point in points),
                "bytes_recv": sum(int(point["bytes_recv"] or 0) for point in points),
                "peak_upload_bps": max((point["upload_bps"] or 0) for point in points) if points else 0,
                "peak_download_bps": max((point["download_bps"] or 0) for point in points) if points else 0,
            },
        }
    )


@api.get("/traffic/live")
def traffic_live():
    limit = _int_arg("points", 60, 1, 300)
    iface = _interface_arg(_selected_interface())
    if not iface:
        return ok({"interface": "", "points": []})
    return ok({"interface": iface, "points": db().recent_samples(iface, limit)})


@api.get("/traffic/daily")
def traffic_daily():
    days = _int_arg("days", 14, 1, 365)
    iface = request.args.get("interface", "").strip() or None
    return ok({"days": days, "interface": iface, "daily": db().daily_stats(days, iface)})


@api.get("/traffic/summary")
def traffic_summary():
    settings = db().get_settings()
    iface = request.args.get("interface", "").strip() or _selected_interface(settings)
    today = date.today()
    week = today - timedelta(days=6)
    month = today - timedelta(days=29)
    return ok(
        {
            "interface": iface,
            "today": db().totals_between(today.isoformat(), today.isoformat(), iface or None),
            "week": db().totals_between(week.isoformat(), today.isoformat(), iface or None),
            "month": db().totals_between(month.isoformat(), today.isoformat(), iface or None),
            "lifetime": db().lifetime_totals(),
        }
    )


@api.get("/traffic/export.csv")
def export_traffic():
    days = _int_arg("days", 30, 1, 365)
    iface = request.args.get("interface", "").strip() or None
    rows = db().daily_stats(days, iface)
    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(
        ["date", "download_bytes", "upload_bytes", "peak_download_bps", "peak_upload_bps", "samples"]
    )
    for row in rows:
        writer.writerow(
            [
                row["date"],
                row["bytes_recv"],
                row["bytes_sent"],
                round(row["download_peak_bps"] or 0, 2),
                round(row["upload_peak_bps"] or 0, 2),
                row["samples"],
            ]
        )
    filename = f"netwatch-traffic-{date.today().isoformat()}.csv"
    return Response(
        output.getvalue().encode("utf-8-sig"),
        mimetype="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# -------------------------------------------------------------------- connections
@api.get("/connections")
def connections():
    state = request.args.get("state", "all").upper()
    if len(state) > 24 or not all(char.isalpha() or char == "_" for char in state):
        raise ApiError("state filter is invalid.")
    data = list_tcp_connections(None if state == "ALL" else state)
    data["timestamp"] = int(time.time())
    return ok(data)


# ------------------------------------------------------------------------ devices
@api.get("/devices")
def devices():
    items = db().list_devices()
    scan = discovery().status()
    if not scan.get("network"):
        interface = resolve_primary_interface(str(db().get_settings().get("interface", "")))
        network = local_network(interface) if interface else None
        if network is not None:
            scan["interface"] = interface
            scan["network"] = str(network)
    last_scan = max((item["last_seen"] for item in items), default=None)
    return ok(
        {
            "devices": items,
            "count": len(items),
            "online": sum(1 for item in items if item["is_online"]),
            "last_scan": last_scan,
            "scan": scan,
        }
    )


@api.post("/devices/scan")
def scan_devices():
    payload = _json_body()
    state = discovery().start(payload.get("confirm") is True)
    _broadcast("scan_started", state)
    return ok(state, 202)


@api.get("/devices/scan/status")
def scan_status():
    return ok(discovery().status())


@api.get("/devices/<int:device_id>/history")
def device_history(device_id: int):
    device = db().get_device(device_id)
    if not device:
        raise ApiError("Device not found.", 404)
    return ok({"device": device, "history": db().device_history(device_id, 120)})


# --------------------------------------------------------------------- diagnostics
@api.post("/diagnostics/ping")
def diagnostics_ping():
    _rate_limit("ping", 1.0)
    payload = _json_body()
    return ok(run_ping(payload.get("host", "")))


@api.post("/diagnostics/dns")
def diagnostics_dns():
    _rate_limit("dns", 1.0)
    payload = _json_body()
    record_type = str(payload.get("record_type", "A")).upper()
    return ok(run_dns(payload.get("host", ""), record_type))


@api.post("/diagnostics/traceroute")
def diagnostics_traceroute():
    _rate_limit("traceroute", 5.0)
    payload = _json_body()
    return ok(run_traceroute(payload.get("host", "")))


@api.get("/diagnostics/connectivity")
def diagnostics_connectivity():
    _rate_limit("connectivity", 2.0)
    return ok(run_connectivity())


# ----------------------------------------------------------------------- analytics
@api.get("/analytics/overview")
def analytics_overview():
    days = _int_arg("days", 7, 1, 365)
    start = date.today() - timedelta(days=days - 1)
    start_ts = int(datetime.combine(start, datetime_time.min).timestamp())
    daily = db().daily_stats(days)
    totals = db().totals_between(start.isoformat(), date.today().isoformat())
    usage = db().interface_usage(start.isoformat(), date.today().isoformat())
    alert_counts = db().alert_summary(start_ts)
    average_download = totals["bytes_recv"] * 8 / (days * 86400) if totals["bytes_recv"] else 0
    average_upload = totals["bytes_sent"] * 8 / (days * 86400) if totals["bytes_sent"] else 0
    return ok(
        {
            "days": days,
            "daily": daily,
            "totals": totals,
            "average_download_bps": round(average_download, 2),
            "average_upload_bps": round(average_upload, 2),
            "interfaces": usage,
            "connectivity": db().connectivity_summary(start_ts),
            "devices": {
                "known": len(db().list_devices()),
                "discovered": db().devices_discovered_since(start_ts),
            },
            "alerts": {
                "total": sum(item["count"] for item in alert_counts),
                "by_type": alert_counts,
            },
        }
    )


@api.get("/analytics/bandwidth")
def analytics_bandwidth():
    days = _int_arg("days", 7, 1, 365)
    iface = _interface_arg(_selected_interface())
    since = int(time.time()) - days * 86400
    hourly = db().hourly_history(iface, since) if iface else []
    return ok({"days": days, "interface": iface, "hourly": hourly, "daily": db().daily_stats(days, iface or None)})


@api.get("/analytics/devices")
def analytics_devices():
    days = _int_arg("days", 30, 1, 365)
    since = int(time.time()) - days * 86400
    return ok(
        {
            "days": days,
            "timeline": db().discovery_timeline(since),
            "devices": db().list_devices(),
            "known": len(db().list_devices()),
            "discovered": db().devices_discovered_since(since),
        }
    )


# -------------------------------------------------------------------------- alerts
@api.get("/alerts")
def list_alerts():
    limit = _int_arg("limit", 100, 1, 500)
    unread_only = request.args.get("unread", "").lower() in {"1", "true", "yes"}
    return ok(
        {
            "alerts": db().list_alerts(limit, unread_only),
            "unread": db().unread_alert_count(),
        }
    )


@api.post("/alerts/<int:alert_id>/ack")
def acknowledge_alert(alert_id: int):
    if not db().acknowledge_alert(alert_id):
        raise ApiError("Alert not found.", 404)
    unread = db().unread_alert_count()
    _broadcast("alerts_updated", {"unread": unread})
    return ok({"unread": unread})


@api.post("/alerts/ack-all")
def acknowledge_all():
    updated = db().acknowledge_all_alerts()
    _broadcast("alerts_updated", {"unread": 0})
    return ok({"acknowledged": updated, "unread": 0})


@api.post("/alerts/clear")
def clear_alerts():
    deleted = db().clear_alerts()
    _broadcast("alerts_updated", {"unread": 0})
    return ok({"deleted": deleted, "unread": 0})


# ------------------------------------------------------------------------ settings
@api.get("/settings")
def get_settings():
    return ok(db().get_settings())


@api.put("/settings")
def update_settings():
    payload = _json_body()
    cleaned = validate_settings_payload(payload)
    if "interface" in cleaned and cleaned["interface"]:
        names = {item["name"] for item in get_interfaces()["interfaces"]}
        if cleaned["interface"] not in names:
            raise ApiError("The selected interface does not exist on this machine.")
    settings = db().save_settings(cleaned)
    monitor().reload_settings()
    if "retention_days" in cleaned:
        db().cleanup(settings["retention_days"])
    _broadcast("settings_updated", settings)
    return ok(settings)


@api.post("/settings/reset")
def reset_settings():
    settings = db().save_settings(dict(DEFAULT_SETTINGS))
    monitor().reload_settings()
    _broadcast("settings_updated", settings)
    return ok(settings)
