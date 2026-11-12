"""Tests for rate calculation and counter-anomaly detection."""

from __future__ import annotations

from backend.app.metrics import compute_rate, counter_delta_is_plausible


def test_compute_rate_converts_bytes_to_bits_per_second():
    sample = compute_rate(1_000, 2_000, 2_000, 4_000, 2.0)
    assert sample.bytes_sent == 1_000
    assert sample.bytes_recv == 2_000
    assert sample.upload_bps == 4_000
    assert sample.download_bps == 8_000


def test_compute_rate_handles_zero_and_negative_elapsed_time():
    assert compute_rate(10, 10, 20, 20, 0).upload_bps == 0
    assert compute_rate(10, 10, 20, 20, -1).download_bps == 0


def test_compute_rate_discards_counter_resets():
    sample = compute_rate(100_000, 200_000, 10, 20, 2.0)
    assert sample.bytes_sent == 0
    assert sample.bytes_recv == 0
    assert sample.upload_bps == 0
    assert sample.download_bps == 0


def test_counter_delta_accepts_normal_ethernet_frames():
    assert counter_delta_is_plausible(60_000, 40, elapsed_seconds=2, link_speed_mbps=1000)


def test_counter_delta_accepts_idle_interval():
    assert counter_delta_is_plausible(0, 0)
    assert counter_delta_is_plausible(0, -3)


def test_counter_delta_rejects_bytes_without_packets():
    assert not counter_delta_is_plausible(1_000_000, 0)


def test_counter_delta_rejects_impossible_frame_size():
    assert not counter_delta_is_plausible(65_536, 1)


def test_counter_delta_rejects_reset_and_rate_above_link_speed():
    assert not counter_delta_is_plausible(-1, 5)
    assert not counter_delta_is_plausible(10_000_000, 2_000, elapsed_seconds=1, link_speed_mbps=10)


def test_counter_delta_allows_burst_within_link_speed():
    assert counter_delta_is_plausible(10_000_000, 10_000, elapsed_seconds=1, link_speed_mbps=100)
