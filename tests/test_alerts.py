"""Tests for alert deduplication and realtime notification delivery."""

from __future__ import annotations

from backend.app.services.alerts import AlertService


class RecordingSocket:
    def __init__(self):
        self.events = []

    def emit(self, event, payload):
        self.events.append((event, payload))


def test_trigger_persists_alert(app, database):
    service = AlertService(database, None, app)
    record = service.trigger("internet_down", "critical", "Internet unreachable", now=1_000)
    assert record["type"] == "internet_down"
    assert record["severity"] == "critical"
    assert record["acknowledged"] == 0
    assert database.unread_alert_count() == 1


def test_trigger_deduplicates_within_cooldown(app, database):
    service = AlertService(database, None, app)
    assert service.trigger("high_download", "warning", "High download", dedupe_seconds=300, now=1_000)
    assert service.trigger("high_download", "warning", "High download", dedupe_seconds=300, now=1_100) is None
    assert service.trigger("high_download", "warning", "High download", dedupe_seconds=300, now=1_300) is not None
    assert database.unread_alert_count() == 2


def test_trigger_allows_different_types_and_zero_cooldown(app, database):
    service = AlertService(database, None, app)
    assert service.trigger("internet_down", "critical", "Down", dedupe_seconds=300, now=2_000)
    assert service.trigger("adapter_down", "warning", "Adapter", dedupe_seconds=300, now=2_000)
    assert service.trigger("internet_down", "critical", "Down again", dedupe_seconds=0, now=2_001)
    assert database.unread_alert_count() == 3


def test_trigger_uses_configured_default_cooldown(app, database):
    database.save_settings({"alert_cooldown_seconds": 30})
    service = AlertService(database, None, app)
    assert service.trigger("test", "info", "First", now=5_000)
    assert service.trigger("test", "info", "Second", now=5_029) is None
    assert service.trigger("test", "info", "Third", now=5_030) is not None


def test_trigger_emits_realtime_event(app, database):
    socket = RecordingSocket()
    service = AlertService(database, socket, app)
    record = service.trigger("test", "info", "Realtime", dedupe_seconds=0, now=1_000)
    assert socket.events == [("alert", record)]
