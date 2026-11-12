"""Tests for settings, target, and discovery-boundary validation."""

from __future__ import annotations

import socket
from types import SimpleNamespace

import pytest

from backend.app.config import ValidationError, validate_settings_payload
from backend.app.services import interfaces
from backend.app.services.diagnostics import validate_target
from backend.app.services.interfaces import normalize_mac


def test_settings_accepts_partial_valid_payload():
    assert validate_settings_payload({}) == {}
    cleaned = validate_settings_payload(
        {
            "refresh_interval": 3,
            "download_threshold_mbps": 250.456,
            "upload_threshold_mbps": 0,
            "notifications_enabled": False,
            "interface": "  Wi-Fi  ",
            "chart_points": 90,
        }
    )
    assert cleaned == {
        "refresh_interval": 3,
        "download_threshold_mbps": 250.46,
        "upload_threshold_mbps": 0.0,
        "notifications_enabled": False,
        "interface": "Wi-Fi",
        "chart_points": 90,
    }


@pytest.mark.parametrize(
    "payload, message",
    [
        ([], "JSON object"),
        ({"unknown": 1}, "Unknown setting"),
        ({"refresh_interval": True}, "integer"),
        ({"refresh_interval": 2.5}, "integer"),
        ({"refresh_interval": 0}, "between 1 and 30"),
        ({"refresh_interval": 31}, "between 1 and 30"),
        ({"download_threshold_mbps": "10"}, "must be a number"),
        ({"download_threshold_mbps": -1}, "between"),
        ({"interface": 5}, "must be a string"),
        ({"interface": "bad\x00name"}, "invalid"),
        ({"notifications_enabled": 1}, "true or false"),
        ({"chart_points": 20.0}, "integer"),
        ({"chart_points": 19}, "between 20 and 300"),
        ({"retention_days": 0}, "between 1 and 365"),
        ({"alert_cooldown_seconds": 10}, "between 30 and 3600"),
        ({"discovery_timeout_ms": 5000}, "between 100 and 2000"),
    ],
)
def test_settings_rejects_invalid_payload(payload, message):
    with pytest.raises(ValidationError, match=message):
        validate_settings_payload(payload)


def test_settings_rejects_very_long_interface_name():
    with pytest.raises(ValidationError, match="interface name is invalid"):
        validate_settings_payload({"interface": "x" * 129})


@pytest.mark.parametrize(
    "raw, expected",
    [
        ("8.8.8.8", "8.8.8.8"),
        (" 1.1.1.1 ", "1.1.1.1"),
        ("2001:4860:4860::8888", "2001:4860:4860::8888"),
        ("Example.COM", "example.com"),
        ("router.local.", "router.local"),
    ],
)
def test_validate_target_accepts_ip_and_hostnames(raw, expected):
    assert validate_target(raw) == expected


@pytest.mark.parametrize(
    "raw",
    [
        None,
        123,
        "",
        "   ",
        "-leading.example.com",
        "two words.example.com",
        "http://example.com",
        "999.999.999.999",
        "under_score.example.com",
        "fe80::1%eth0",
        "x" * 254,
    ],
)
def test_validate_target_rejects_unsafe_input(raw):
    with pytest.raises(ValidationError):
        validate_target(raw)


def test_normalize_mac_variants():
    assert normalize_mac("aa-bb-cc-dd-ee-ff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("aabb.ccdd.eeff") == "AA:BB:CC:DD:EE:FF"
    assert normalize_mac("00:00:00:00:00:00") is None
    assert normalize_mac("not-a-mac") is None
    assert normalize_mac(None) is None


def _fake_addrs(address: str, netmask: str):
    return {"Wi-Fi": [SimpleNamespace(family=socket.AF_INET, address=address, netmask=netmask)]}


def test_local_network_limits_private_subnet(monkeypatch):
    monkeypatch.setattr(interfaces.psutil, "net_if_addrs", lambda: _fake_addrs("192.168.1.44", "255.255.0.0"))
    network = interfaces.local_network("Wi-Fi")
    assert str(network) == "192.168.1.0/24"
    assert network.is_private


def test_local_network_accepts_smaller_private_subnet(monkeypatch):
    monkeypatch.setattr(interfaces.psutil, "net_if_addrs", lambda: _fake_addrs("10.0.0.14", "255.255.255.128"))
    network = interfaces.local_network("Wi-Fi")
    assert str(network) == "10.0.0.0/25"


def test_local_network_rejects_public_and_loopback(monkeypatch):
    monkeypatch.setattr(interfaces.psutil, "net_if_addrs", lambda: _fake_addrs("8.8.8.9", "255.255.255.0"))
    assert interfaces.local_network("Wi-Fi") is None

    monkeypatch.setattr(interfaces.psutil, "net_if_addrs", lambda: _fake_addrs("127.0.0.1", "255.0.0.0"))
    assert interfaces.local_network("Wi-Fi") is None

    monkeypatch.setattr(interfaces.psutil, "net_if_addrs", lambda: _fake_addrs("169.254.10.2", "255.255.0.0"))
    assert interfaces.local_network("Wi-Fi") is None


def test_local_network_rejects_unknown_interface(monkeypatch):
    monkeypatch.setattr(interfaces.psutil, "net_if_addrs", lambda: {"Wi-Fi": []})
    assert interfaces.local_network("Missing NIC") is None
    assert interfaces.local_network(None) is None
