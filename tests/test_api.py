"""Integration tests for every page and JSON API area."""

from __future__ import annotations

import time

import pytest

from backend.app.routes import api as api_module

PAGES = [
    "/",
    "/interfaces",
    "/traffic",
    "/devices",
    "/connections",
    "/diagnostics",
    "/analytics",
    "/alerts",
    "/settings",
]


@pytest.fixture(autouse=True)
def clear_rate_limits():
    api_module._state.clear()
    yield
    api_module._state.clear()


def test_pages_render(client):
    for path in PAGES:
        response = client.get(path)
        assert response.status_code == 200, path
        assert b"NETWATCH" in response.data, path
        assert response.headers["X-Frame-Options"] == "DENY"
        assert "default-src 'self'" in response.headers["Content-Security-Policy"]


def test_missing_page_and_api_return_useful_errors(client):
    page = client.get("/does-not-exist")
    assert page.status_code == 404
    assert b"NETWATCH" in page.data

    response = client.get("/api/does-not-exist")
    assert response.status_code == 404
    assert response.is_json
    assert response.get_json() == {"ok": False, "error": "API endpoint not found."}


def test_health_and_dashboard(client):
    health = client.get("/api/health")
    assert health.status_code == 200
    payload = health.get_json()
    assert payload["ok"] is True
    assert payload["data"]["status"] == "ok"
    assert payload["data"]["monitor_running"] is False

    dashboard = client.get("/api/dashboard/summary").get_json()
    assert dashboard["ok"] is True
    data = dashboard["data"]
    assert {"monitor", "today", "lifetime", "interface", "settings", "unread_alerts", "system"} <= set(data)
    assert data["unread_alerts"] == 0


def test_interfaces_endpoint(client):
    response = client.get("/api/interfaces")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert isinstance(data["interfaces"], list)
    assert data["count"] == len(data["interfaces"])
    assert "selected_setting" in data


def test_traffic_endpoints_use_persisted_samples(client, database):
    now = int(time.time())
    database.insert_sample(now, "Ethernet", 1_000, 4_000, 8_000, 32_000)

    history = client.get("/api/traffic/history?range=24h&interface=Ethernet").get_json()
    assert history["ok"] is True
    assert history["data"]["interface"] == "Ethernet"
    assert history["data"]["summary"]["bytes_recv"] == 4_000
    assert len(history["data"]["points"]) == 1

    live = client.get("/api/traffic/live?points=1&interface=Ethernet").get_json()
    assert live["data"]["points"][0]["download_bps"] == 32_000

    daily = client.get("/api/traffic/daily?days=7&interface=Ethernet").get_json()
    assert daily["data"]["daily"][0]["bytes_sent"] == 1_000

    summary = client.get("/api/traffic/summary?interface=Ethernet").get_json()
    assert summary["data"]["today"]["bytes_recv"] == 4_000
    assert summary["data"]["lifetime"]["samples"] == 1


@pytest.mark.parametrize(
    "path",
    [
        "/api/traffic/history?range=2h",
        "/api/traffic/live?points=0",
        "/api/traffic/live?points=301",
        "/api/traffic/live?points=abc",
        "/api/traffic/daily?days=0",
        "/api/alerts?limit=0",
        "/api/alerts?limit=501",
        "/api/analytics/overview?days=0",
        "/api/analytics/bandwidth?days=366",
    ],
)
def test_query_validation(client, path):
    response = client.get(path)
    assert response.status_code == 400
    assert response.get_json()["ok"] is False


def test_csv_export(client, database):
    database.insert_sample(int(time.time()), "Wi-Fi", 1_500, 2_500, 3_000, 4_000)
    response = client.get("/api/traffic/export.csv?days=7")
    assert response.status_code == 200
    assert response.mimetype == "text/csv"
    assert "attachment; filename=\"netwatch-traffic-" in response.headers["Content-Disposition"]
    text = response.data.decode("utf-8-sig")
    assert text.startswith("date,download_bytes,upload_bytes")
    assert "Wi-Fi" not in text  # exports daily totals, not adapter names
    assert ",2500,1500," in text


def test_connections_endpoint(client):
    response = client.get("/api/connections")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert "connections" in data
    assert isinstance(data["connections"], list)
    assert data["timestamp"] > 0

    invalid = client.get("/api/connections?state=LISTEN;DELETE")
    assert invalid.status_code == 400


def test_device_inventory_and_scan_safety(client):
    response = client.get("/api/devices")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["devices"] == []
    assert data["count"] == 0
    assert data["scan"]["running"] is False

    refused = client.post("/api/devices/scan", json={"confirm": False})
    assert refused.status_code == 400
    assert "authorized" in refused.get_json()["error"]

    refused_string = client.post("/api/devices/scan", json={"confirm": "true"})
    assert refused_string.status_code == 400

    status = client.get("/api/devices/scan/status")
    assert status.status_code == 200
    assert status.get_json()["data"]["running"] is False

    missing = client.get("/api/devices/99999/history")
    assert missing.status_code == 404
    assert missing.get_json() == {"ok": False, "error": "Device not found."}


def test_device_history_endpoint(client, database):
    database.scan_devices(
        "Wi-Fi",
        [{"ip": "192.168.1.20", "mac": "AA:BB:CC:DD:EE:20", "hostname": "laptop"}],
        1_700_000_000,
    )
    device = client.get("/api/devices").get_json()["data"]["devices"][0]
    response = client.get(f"/api/devices/{device['id']}/history")
    assert response.status_code == 200
    data = response.get_json()["data"]
    assert data["device"]["hostname"] == "laptop"
    assert len(data["history"]) == 1


def test_diagnostics_reject_unsafe_input(client):
    ping = client.post("/api/diagnostics/ping", json={"host": "8.8.8.8 & whoami"})
    assert ping.status_code == 400
    assert ping.get_json()["ok"] is False

    dns = client.post("/api/diagnostics/dns", json={"host": "example.com", "record_type": "BOGUS"})
    assert dns.status_code == 400

    traceroute = client.post("/api/diagnostics/traceroute", json={"host": "-oops"})
    assert traceroute.status_code == 400

    second = client.post("/api/diagnostics/ping", json={"host": "bad host"})
    assert second.status_code == 429


def test_diagnostics_success_shapes(client, monkeypatch):
    monkeypatch.setattr(
        api_module,
        "run_ping",
        lambda host: {
            "target": host,
            "sent": 4,
            "received": 4,
            "loss_percent": 0,
            "min_ms": 1.0,
            "max_ms": 2.0,
            "avg_ms": 1.5,
            "success": True,
            "output": "",
        },
    )
    response = client.post("/api/diagnostics/ping", json={"host": "8.8.8.8"})
    assert response.status_code == 200
    assert response.get_json()["data"]["success"] is True

    monkeypatch.setattr(
        api_module,
        "run_connectivity",
        lambda: {"targets": [], "online": True, "duration_ms": 1.0},
    )
    connectivity = client.get("/api/diagnostics/connectivity")
    assert connectivity.status_code == 200
    assert connectivity.get_json()["data"]["online"] is True


def test_analytics_endpoints(client, database):
    now = int(time.time())
    database.insert_sample(now, "Ethernet", 2_000, 8_000, 16_000, 64_000)
    database.record_connectivity(now, True, 12.0, "TCP")
    database.create_alert(now, "high_download", "warning", "High download")
    database.scan_devices(
        "Ethernet",
        [{"ip": "192.168.1.30", "mac": None, "hostname": "nas"}],
        now,
    )

    overview = client.get("/api/analytics/overview?days=7").get_json()["data"]
    assert overview["days"] == 7
    assert overview["totals"]["bytes_recv"] == 8_000
    assert overview["connectivity"]["uptime_percent"] == 100.0
    assert overview["devices"]["known"] == 1
    assert overview["alerts"]["total"] == 1

    bandwidth = client.get("/api/analytics/bandwidth?days=7&interface=Ethernet").get_json()["data"]
    assert bandwidth["interface"] == "Ethernet"
    assert bandwidth["hourly"][0]["download_bps"] == 64_000

    devices = client.get("/api/analytics/devices?days=30").get_json()["data"]
    assert devices["known"] == 1
    assert devices["timeline"][0]["devices"] == 1


def test_alert_lifecycle_api(client, database):
    first = database.create_alert(int(time.time()), "internet_down", "critical", "Offline")
    database.create_alert(int(time.time()), "adapter_down", "warning", "Adapter down")

    listing = client.get("/api/alerts?limit=10").get_json()["data"]
    assert len(listing["alerts"]) == 2
    assert listing["unread"] == 2

    unread = client.get("/api/alerts?unread=true").get_json()["data"]
    assert len(unread["alerts"]) == 2

    ack = client.post(f"/api/alerts/{first['id']}/ack", json={})
    assert ack.status_code == 200
    assert ack.get_json()["data"]["unread"] == 1

    missing = client.post("/api/alerts/999999/ack", json={})
    assert missing.status_code == 404

    ack_all = client.post("/api/alerts/ack-all", json={})
    assert ack_all.get_json()["data"] == {"acknowledged": 1, "unread": 0}

    cleared = client.post("/api/alerts/clear", json={})
    assert cleared.get_json()["data"] == {"deleted": 2, "unread": 0}
    assert client.get("/api/alerts").get_json()["data"]["alerts"] == []


def test_settings_api_round_trip(client):
    current = client.get("/api/settings").get_json()["data"]
    assert current["refresh_interval"] == 2
    assert current["chart_points"] == 300

    updated = client.put(
        "/api/settings",
        json={"refresh_interval": 5, "compact_mode": True, "retention_days": 14},
    )
    assert updated.status_code == 200
    settings = updated.get_json()["data"]
    assert settings["refresh_interval"] == 5
    assert settings["compact_mode"] is True
    assert settings["retention_days"] == 14

    invalid = client.put("/api/settings", json={"refresh_interval": 0})
    assert invalid.status_code == 400
    assert "between 1 and 30" in invalid.get_json()["error"]

    unknown = client.put("/api/settings", json={"nope": 1})
    assert unknown.status_code == 400

    reset = client.post("/api/settings/reset", json={})
    assert reset.status_code == 200
    assert reset.get_json()["data"]["refresh_interval"] == 2
    assert reset.get_json()["data"]["compact_mode"] is False


def test_interface_selection_validation(client):
    response = client.post("/api/interfaces/select", json={"interface": "Definitely Missing NIC"})
    assert response.status_code == 400
    assert "does not exist" in response.get_json()["error"]


def test_mutation_security_guards(client):
    no_json = client.post("/api/settings/reset", data="{}", content_type="text/plain")
    assert no_json.status_code == 415

    cross_site = client.post(
        "/api/settings/reset",
        json={},
        headers={"Origin": "http://evil.example"},
    )
    assert cross_site.status_code == 403
    assert "Cross-origin" in cross_site.get_json()["error"]

    cross_site_fetch = client.post(
        "/api/settings/reset",
        json={},
        headers={"Sec-Fetch-Site": "cross-site"},
    )
    assert cross_site_fetch.status_code == 403

    non_object = client.post("/api/devices/scan", json=["not", "an", "object"])
    assert non_object.status_code == 400
    assert "JSON object" in non_object.get_json()["error"]
