"""Tests for diagnostics parsing and safe command construction."""

from __future__ import annotations

import pytest

from backend.app.config import ValidationError
from backend.app.services import diagnostics

WINDOWS_PING = """
Pinging 8.8.8.8 with 32 bytes of data:
Reply from 8.8.8.8: bytes=32 time=12ms TTL=117
Reply from 8.8.8.8: bytes=32 time=15ms TTL=117
Reply from 8.8.8.8: bytes=32 time=11ms TTL=117
Reply from 8.8.8.8: bytes=32 time=13ms TTL=117

Ping statistics for 8.8.8.8:
    Packets: Sent = 4, Received = 4, Lost = 0 (0% loss),
Approximate round trip times in milli-seconds:
    Minimum = 11ms, Maximum = 15ms, Average = 12ms
"""

WINDOWS_PING_LOSS = """
Pinging 192.0.2.1 with 32 bytes of data:
Request timed out.
Request timed out.
Reply from 192.0.2.1: bytes=32 time=8ms TTL=64

Ping statistics for 192.0.2.1:
    Packets: Sent = 3, Received = 1, Lost = 2 (66% loss),
"""


def test_parse_windows_ping_summary():
    parsed = diagnostics.parse_ping_output(WINDOWS_PING)
    assert parsed == {
        "sent": 4,
        "received": 4,
        "loss_percent": 0,
        "min_ms": 11.0,
        "max_ms": 15.0,
        "avg_ms": 12.0,
        "success": True,
    }


def test_parse_windows_ping_loss():
    parsed = diagnostics.parse_ping_output(WINDOWS_PING_LOSS, expected=3)
    assert parsed["sent"] == 3
    assert parsed["received"] == 1
    assert parsed["loss_percent"] == 66
    assert parsed["success"] is True


def test_parse_ping_without_summary_uses_ttl_replies():
    output = "Reply from 1.1.1.1: bytes=32 time=9ms TTL=57\nReply from 1.1.1.1: bytes=32 time=<1ms TTL=57"
    parsed = diagnostics.parse_ping_output(output, expected=4)
    assert parsed["received"] == 2
    assert parsed["loss_percent"] == 50
    assert parsed["min_ms"] == 1.0
    assert parsed["success"] is True


def test_parse_ping_with_no_replies():
    parsed = diagnostics.parse_ping_output("Request timed out.\nRequest timed out.", expected=2)
    assert parsed["sent"] == 2
    assert parsed["received"] == 0
    assert parsed["loss_percent"] == 100
    assert parsed["success"] is False
    assert parsed["min_ms"] is None


def test_parse_traceroute_skips_header_and_keeps_stars():
    output = """
Tracing route to dns.google [8.8.8.8]
over a maximum of 30 hops:

  1     2 ms     1 ms     1 ms  192.168.1.1
  2     *        *        *     Request timed out.
  3    10 ms    11 ms    12 ms  10.0.0.1
Trace complete.
"""
    hops = diagnostics.parse_traceroute_output(output)
    assert [hop["hop"] for hop in hops] == [1, 2, 3]
    assert hops[0]["ip"] == "192.168.1.1"
    assert hops[0]["times_ms"] == [2.0, 1.0, 1.0]
    assert hops[1]["ip"] is None
    assert hops[1]["times_ms"] == []
    assert hops[2]["ip"] == "10.0.0.1"


def test_run_ping_uses_argument_array_and_timeout(monkeypatch):
    captured = {}

    def fake_run(args, timeout):
        captured["args"] = args
        captured["timeout"] = timeout
        return WINDOWS_PING.strip(), 0, 250.0, False

    monkeypatch.setattr(diagnostics, "_run", fake_run)
    result = diagnostics.run_ping("8.8.8.8", count=4, timeout_ms=1000)
    assert captured["args"][0] == "ping"
    assert "8.8.8.8" in captured["args"]
    assert isinstance(captured["args"], list)
    assert captured["timeout"] > 0
    assert result["target"] == "8.8.8.8"
    assert result["timed_out"] is False
    assert result["return_code"] == 0
    assert result["output"].startswith("Pinging")


def test_run_traceroute_uses_bounded_hops(monkeypatch):
    captured = {}

    def fake_run(args, timeout):
        captured["args"] = args
        captured["timeout"] = timeout
        return "  1     2 ms     1 ms     1 ms  192.168.1.1", 0, 900.0, False

    monkeypatch.setattr(diagnostics, "_run", fake_run)
    result = diagnostics.run_traceroute("example.com", max_hops=12)
    assert captured["args"][0] in {"tracert", "traceroute"}
    assert "12" in captured["args"]
    assert result["hop_count"] == 1
    assert result["completed"] is True


def test_run_ping_rejects_unsafe_target_before_spawning(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("subprocess must not run for invalid input")

    monkeypatch.setattr(diagnostics, "_run", fail)
    with pytest.raises(ValidationError):
        diagnostics.run_ping("8.8.8.8 & whoami")


def test_run_dns_rejects_invalid_record_type_before_network(monkeypatch):
    def fail(*_args, **_kwargs):
        raise AssertionError("resolver must not be created for invalid record type")

    monkeypatch.setattr(diagnostics.dns.resolver, "Resolver", fail)
    with pytest.raises(ValidationError):
        diagnostics.run_dns("example.com", "SCRIPT")


def test_run_dns_formats_resolver_answers(monkeypatch):
    class FakeAnswer:
        def __iter__(self):
            return iter([FakeRecord("93.184.216.34"), FakeRecord("93.184.216.35")])

    class FakeRecord:
        def __init__(self, value):
            self.value = value

        def to_text(self):
            return self.value

    class FakeResolver:
        def __init__(self, configure=True):
            self.nameservers = ["10.0.0.1"]
            self.timeout = 0
            self.lifetime = 0

        def resolve(self, target, record_type, lifetime=5):
            assert target == "example.com"
            assert record_type == "A"
            return FakeAnswer()

    monkeypatch.setattr(diagnostics.dns.resolver, "Resolver", FakeResolver)
    result = diagnostics.run_dns("Example.com", "a")
    assert result["target"] == "example.com"
    assert result["record_type"] == "A"
    assert result["records"] == ["93.184.216.34", "93.184.216.35"]
    assert result["resolved"] is True
    assert result["nameserver"] == "10.0.0.1"
    assert result["error"] is None
