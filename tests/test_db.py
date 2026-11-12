"""Tests for SQLite persistence and aggregation."""

from __future__ import annotations

import time

from backend.app.db import Database


def make_database(tmp_path) -> Database:
    database = Database(tmp_path / "db.sqlite")
    database.initialize()
    return database


def test_settings_round_trip(tmp_path):
    database = make_database(tmp_path)
    defaults = database.get_settings()
    assert defaults["refresh_interval"] == 2
    updated = database.save_settings({"refresh_interval": 5, "compact_mode": True})
    assert updated["refresh_interval"] == 5
    assert updated["compact_mode"] is True
    assert database.get_settings()["refresh_interval"] == 5


def test_samples_and_daily_aggregates(tmp_path):
    database = make_database(tmp_path)
    now = int(time.time())
    database.insert_sample(now, "Ethernet", 1_000, 4_000, 8_000, 32_000)
    database.insert_sample(now + 2, "Ethernet", 2_000, 6_000, 16_000, 48_000)

    recent = database.recent_samples("Ethernet", 10)
    assert len(recent) == 2
    assert recent[0]["ts"] < recent[1]["ts"]

    today = database.today_totals("Ethernet")
    assert today["bytes_sent"] == 3_000
    assert today["bytes_recv"] == 10_000
    assert today["download_peak_bps"] == 48_000
    assert today["samples"] == 2

    daily = database.daily_stats(7, "Ethernet")
    assert len(daily) == 1
    assert daily[0]["bytes_recv"] == 10_000


def test_traffic_history_buckets_rows(tmp_path):
    database = make_database(tmp_path)
    now = 1_700_000_030  # Fixed timestamp, mid-bucket, so both samples share a minute.
    database.insert_sample(now - 5, "Wi-Fi", 100, 200, 400, 800)
    database.insert_sample(now, "Wi-Fi", 100, 200, 400, 800)
    buckets = database.traffic_history("Wi-Fi", now - 60, 60)
    assert len(buckets) == 1
    assert buckets[0]["bytes_recv"] == 400
    assert buckets[0]["download_bps"] == 800


def test_device_scan_persists_devices_and_history(tmp_path):
    database = make_database(tmp_path)
    ts = 1_700_000_000
    result = database.scan_devices(
        "Wi-Fi",
        [
            {"ip": "192.168.1.10", "mac": "AA:BB:CC:DD:EE:01", "hostname": "router"},
            {"ip": "192.168.1.11", "mac": "AA:BB:CC:DD:EE:02", "hostname": ""},
        ],
        ts,
    )
    assert result == {"found": 2, "new": 2, "known": 2}

    devices = database.list_devices()
    assert len(devices) == 2
    assert all(device["is_online"] == 1 for device in devices)
    assert database.devices_discovered_since(0) == 2

    router = next(device for device in devices if device["ip"] == "192.168.1.10")
    history = database.device_history(router["id"])
    assert len(history) == 1
    assert history[0]["online"] == 1

    second = database.scan_devices(
        "Wi-Fi",
        [{"ip": "192.168.1.10", "mac": None, "hostname": "router"}],
        ts + 60,
    )
    assert second["found"] == 1
    assert second["known"] == 2
    updated = next(
        device for device in database.list_devices() if device["ip"] == "192.168.1.11"
    )
    assert updated["is_online"] == 0
    assert len(database.device_history(router["id"])) == 2


def test_alert_lifecycle(tmp_path):
    database = make_database(tmp_path)
    alert = database.create_alert(100, "internet_down", "critical", "Offline")
    assert database.unread_alert_count() == 1
    assert database.list_alerts(10)[0]["message"] == "Offline"
    assert database.alert_summary(0)[0]["count"] == 1

    assert database.acknowledge_alert(alert["id"]) is True
    assert database.unread_alert_count() == 0
    assert database.acknowledge_alert(999_999) is False

    database.create_alert(101, "test", "info", "Another")
    assert database.acknowledge_all_alerts() == 1
    assert database.clear_alerts() == 2
    assert database.list_alerts(10) == []


def test_connectivity_summary(tmp_path):
    database = make_database(tmp_path)
    database.record_connectivity(100, True, 10.0, "TCP")
    database.record_connectivity(101, False, None, None)
    database.record_connectivity(102, True, 20.0, "TCP")
    summary = database.connectivity_summary(0)
    assert summary["total"] == 3
    assert summary["online"] == 2
    assert summary["uptime_percent"] == 66.7
    assert summary["avg_latency_ms"] == 15.0


def test_cleanup_removes_old_records(tmp_path):
    database = make_database(tmp_path)
    now = int(time.time())
    old = now - 40 * 86400
    database.insert_sample(old, "Ethernet", 100, 200, 400, 800)
    database.insert_sample(now, "Ethernet", 100, 200, 400, 800)
    database.create_alert(old, "old", "info", "Old alert")
    database.record_connectivity(old, True, 10.0, "TCP")

    removed = database.cleanup(30)
    assert removed["samples"] == 1
    assert removed["daily_stats"] == 1
    assert removed["alerts"] == 1
    assert removed["connectivity_checks"] == 1
    assert database.lifetime_totals()["samples"] == 1


def test_interface_names_and_health(tmp_path):
    database = make_database(tmp_path)
    now = int(time.time())
    database.insert_sample(now, "Wi-Fi", 10, 20, 40, 80)
    assert database.interface_names() == ["Wi-Fi"]
    assert database.ping() is True
    assert database.database_size() > 0
