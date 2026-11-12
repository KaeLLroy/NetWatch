"""Pure network metric calculations (unit-testable)."""

from __future__ import annotations

from dataclasses import dataclass

MAX_BYTES_PER_PACKET = 65_535


@dataclass(frozen=True)
class RateSample:
    bytes_sent: int
    bytes_recv: int
    upload_bps: float
    download_bps: float


def counter_delta_is_plausible(
    byte_delta: int,
    packet_delta: int,
    *,
    elapsed_seconds: float | None = None,
    link_speed_mbps: float | None = None,
) -> bool:
    """Reject impossible counter jumps caused by adapter resets or driver bugs.

    Windows wireless drivers occasionally double-read or reset their 64-bit
    octet counters during a reconnect. A jump is suspicious when bytes moved
    without corresponding packets, when the implied frame size is impossible,
    or when the implied throughput exceeds the negotiated link rate.
    """
    if byte_delta < 0:
        return False
    if byte_delta == 0:
        return True
    if packet_delta <= 0:
        return False
    if byte_delta / packet_delta > MAX_BYTES_PER_PACKET:
        return False
    if elapsed_seconds and elapsed_seconds > 0 and link_speed_mbps and link_speed_mbps > 0:
        implied_bps = byte_delta * 8 / elapsed_seconds
        if implied_bps > link_speed_mbps * 1_000_000 * 1.5:
            return False
    return True


def compute_rate(
    previous_sent: int,
    previous_recv: int,
    current_sent: int,
    current_recv: int,
    elapsed_seconds: float,
) -> RateSample:
    """Convert cumulative byte counters into per-second rates.

    Negative deltas indicate a counter reset (adapter restart or reboot), so the
    interval is treated as zero rather than reporting an impossible rate.
    """
    if elapsed_seconds <= 0:
        return RateSample(0, 0, 0.0, 0.0)

    sent_delta = current_sent - previous_sent
    recv_delta = current_recv - previous_recv
    if sent_delta < 0 or recv_delta < 0:
        return RateSample(0, 0, 0.0, 0.0)

    return RateSample(
        bytes_sent=sent_delta,
        bytes_recv=recv_delta,
        upload_bps=round(sent_delta * 8 / elapsed_seconds, 2),
        download_bps=round(recv_delta * 8 / elapsed_seconds, 2),
    )
