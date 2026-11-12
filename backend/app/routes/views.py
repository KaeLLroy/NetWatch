"""HTML page routes."""

from __future__ import annotations

from flask import Blueprint, render_template

views = Blueprint("views", __name__)

PAGE_META = {
    "dashboard": ("Network Overview", "Live link telemetry and operational health"),
    "interfaces": ("Network Interfaces", "Adapters, addressing, and link selection"),
    "traffic": ("Traffic Analysis", "Bandwidth history and transfer statistics"),
    "devices": ("Connected Devices", "Authorized local-network discovery"),
    "connections": ("Active Connections", "TCP sessions and owning processes"),
    "diagnostics": ("Network Diagnostics", "Ping, DNS, traceroute, and reachability"),
    "analytics": ("Historical Analytics", "Long-term trends and operational summaries"),
    "alerts": ("Alert Center", "Network events and threshold notifications"),
    "settings": ("Settings", "Monitoring, alerting, and retention preferences"),
}


def _render(page: str):
    title, subtitle = PAGE_META[page]
    return render_template(f"{page}.html", active_page=page, page_title=title, page_subtitle=subtitle)


@views.get("/")
def dashboard():
    return _render("dashboard")


@views.get("/interfaces")
def interfaces_page():
    return _render("interfaces")


@views.get("/traffic")
def traffic_page():
    return _render("traffic")


@views.get("/devices")
def devices_page():
    return _render("devices")


@views.get("/connections")
def connections_page():
    return _render("connections")


@views.get("/diagnostics")
def diagnostics_page():
    return _render("diagnostics")


@views.get("/analytics")
def analytics_page():
    return _render("analytics")


@views.get("/alerts")
def alerts_page():
    return _render("alerts")


@views.get("/settings")
def settings_page():
    return _render("settings")
