"""SQLite persistence layer for NetWatch."""

from __future__ import annotations

import json
import sqlite3
import time
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from .config import DEFAULT_SETTINGS

SCHEMA = """
PRAGMA journal_mode=WAL;
PRAGMA foreign_keys=ON;

CREATE TABLE IF NOT EXISTS settings (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at INTEGER NOT NULL
);

CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    interface TEXT NOT NULL,
    bytes_sent INTEGER NOT NULL DEFAULT 0,
    bytes_recv INTEGER NOT NULL DEFAULT 0,
    upload_bps REAL NOT NULL DEFAULT 0,
    download_bps REAL NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_samples_ts ON samples(ts);
CREATE INDEX IF NOT EXISTS idx_samples_interface_ts ON samples(interface, ts);

CREATE TABLE IF NOT EXISTS daily_stats (
    date TEXT NOT NULL,
    interface TEXT NOT NULL,
    bytes_sent INTEGER NOT NULL DEFAULT 0,
    bytes_recv INTEGER NOT NULL DEFAULT 0,
    upload_peak_bps REAL NOT NULL DEFAULT 0,
    download_peak_bps REAL NOT NULL DEFAULT 0,
    samples INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (date, interface)
);

CREATE TABLE IF NOT EXISTS devices (
    id INTEGER PRIMARY KEY,
    ip TEXT NOT NULL UNIQUE,
    mac TEXT,
    hostname TEXT,
    interface TEXT,
    first_seen INTEGER NOT NULL,
    last_seen INTEGER NOT NULL,
    is_online INTEGER NOT NULL DEFAULT 1
);
CREATE INDEX IF NOT EXISTS idx_devices_last_seen ON devices(last_seen);
CREATE INDEX IF NOT EXISTS idx_devices_interface ON devices(interface);

CREATE TABLE IF NOT EXISTS device_scans (
    id INTEGER PRIMARY KEY,
    device_id INTEGER NOT NULL REFERENCES devices(id) ON DELETE CASCADE,
    ts INTEGER NOT NULL,
    online INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_device_scans_ts ON device_scans(ts);
CREATE INDEX IF NOT EXISTS idx_device_scans_device ON device_scans(device_id, ts);

CREATE TABLE IF NOT EXISTS alerts (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    message TEXT NOT NULL,
    acknowledged INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_alerts_ts ON alerts(ts);

CREATE TABLE IF NOT EXISTS connectivity_checks (
    id INTEGER PRIMARY KEY,
    ts INTEGER NOT NULL,
    online INTEGER NOT NULL,
    latency_ms REAL,
    method TEXT
);
CREATE INDEX IF NOT EXISTS idx_connectivity_ts ON connectivity_checks(ts);
"""


class Database:
    """Thread-safe-by-connection SQLite repository."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)

    @contextmanager
    def _connect(self) -> Iterator[sqlite3.Connection]:
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("PRAGMA busy_timeout=15000")
        try:
            yield connection
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()

    def initialize(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self._connect() as connection:
            connection.executescript(SCHEMA)
            connection.execute("PRAGMA user_version=1")

    # ------------------------------------------------------------------ settings
    def get_settings(self) -> dict[str, Any]:
        settings = dict(DEFAULT_SETTINGS)
        with self._connect() as connection:
            rows = connection.execute("SELECT key, value FROM settings").fetchall()
        for row in rows:
            if row["key"] not in settings:
                continue
            try:
                settings[row["key"]] = json.loads(row["value"])
            except (TypeError, ValueError):
                continue
        return settings

    def save_settings(self, updates: dict[str, Any]) -> dict[str, Any]:
        now = int(time.time())
        with self._connect() as connection:
            for key, value in updates.items():
                connection.execute(
                    """
                    INSERT INTO settings(key, value, updated_at) VALUES(?, ?, ?)
                    ON CONFLICT(key) DO UPDATE SET value=excluded.value,
                                                   updated_at=excluded.updated_at
                    """,
                    (key, json.dumps(value), now),
                )
        return self.get_settings()

    # ------------------------------------------------------------------- samples
    def insert_sample(
        self,
        ts: int,
        interface: str,
        bytes_sent: int,
        bytes_recv: int,
        upload_bps: float,
        download_bps: float,
    ) -> None:
        day = datetime.fromtimestamp(ts).strftime("%Y-%m-%d")
        with self._connect() as connection:
            connection.execute(
                """
                INSERT INTO samples(ts, interface, bytes_sent, bytes_recv, upload_bps, download_bps)
                VALUES(?, ?, ?, ?, ?, ?)
                """,
                (ts, interface, bytes_sent, bytes_recv, upload_bps, download_bps),
            )
            connection.execute(
                """
                INSERT INTO daily_stats(date, interface, bytes_sent, bytes_recv,
                                        upload_peak_bps, download_peak_bps, samples)
                VALUES(?, ?, ?, ?, ?, ?, 1)
                ON CONFLICT(date, interface) DO UPDATE SET
                    bytes_sent = bytes_sent + excluded.bytes_sent,
                    bytes_recv = bytes_recv + excluded.bytes_recv,
                    upload_peak_bps = MAX(upload_peak_bps, excluded.upload_peak_bps),
                    download_peak_bps = MAX(download_peak_bps, excluded.download_peak_bps),
                    samples = samples + 1
                """,
                (day, interface, bytes_sent, bytes_recv, upload_bps, download_bps),
            )

    def recent_samples(self, interface: str, limit: int = 60) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ts, upload_bps, download_bps, bytes_sent, bytes_recv
                FROM samples WHERE interface = ? ORDER BY ts DESC LIMIT ?
                """,
                (interface, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def traffic_history(
        self, interface: str, since_ts: int, bucket_seconds: int
    ) -> list[dict[str, Any]]:
        bucket_seconds = max(1, int(bucket_seconds))
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT (ts / ?) * ? AS bucket_ts,
                       AVG(download_bps) AS download_bps,
                       AVG(upload_bps) AS upload_bps,
                       SUM(bytes_recv) AS bytes_recv,
                       SUM(bytes_sent) AS bytes_sent
                FROM samples
                WHERE interface = ? AND ts >= ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
                """,
                (bucket_seconds, bucket_seconds, interface, since_ts),
            ).fetchall()
        return [dict(row) for row in rows]

    def hourly_history(self, interface: str, since_ts: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT (ts / 3600) * 3600 AS bucket_ts,
                       AVG(download_bps) AS download_bps,
                       AVG(upload_bps) AS upload_bps,
                       SUM(bytes_recv) AS bytes_recv,
                       SUM(bytes_sent) AS bytes_sent
                FROM samples
                WHERE interface = ? AND ts >= ?
                GROUP BY bucket_ts
                ORDER BY bucket_ts
                """,
                (interface, since_ts),
            ).fetchall()
        return [dict(row) for row in rows]

    def daily_stats(self, days: int, interface: str | None = None) -> list[dict[str, Any]]:
        start = (date.today() - timedelta(days=max(1, days) - 1)).isoformat()
        query = """
            SELECT date,
                   SUM(bytes_sent) AS bytes_sent,
                   SUM(bytes_recv) AS bytes_recv,
                   MAX(upload_peak_bps) AS upload_peak_bps,
                   MAX(download_peak_bps) AS download_peak_bps,
                   SUM(samples) AS samples
            FROM daily_stats
            WHERE date >= ?
        """
        params: list[Any] = [start]
        if interface:
            query += " AND interface = ?"
            params.append(interface)
        query += " GROUP BY date ORDER BY date"
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def totals_between(self, start_date: str, end_date: str, interface: str | None = None) -> dict[str, Any]:
        query = """
            SELECT COALESCE(SUM(bytes_sent), 0) AS bytes_sent,
                   COALESCE(SUM(bytes_recv), 0) AS bytes_recv,
                   COALESCE(MAX(upload_peak_bps), 0) AS upload_peak_bps,
                   COALESCE(MAX(download_peak_bps), 0) AS download_peak_bps,
                   COALESCE(SUM(samples), 0) AS samples
            FROM daily_stats
            WHERE date BETWEEN ? AND ?
        """
        params: list[Any] = [start_date, end_date]
        if interface:
            query += " AND interface = ?"
            params.append(interface)
        with self._connect() as connection:
            row = connection.execute(query, params).fetchone()
        return dict(row) if row else {
            "bytes_sent": 0,
            "bytes_recv": 0,
            "upload_peak_bps": 0,
            "download_peak_bps": 0,
            "samples": 0,
        }

    def today_totals(self, interface: str | None = None) -> dict[str, Any]:
        today = date.today().isoformat()
        return self.totals_between(today, today, interface)

    def lifetime_totals(self) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COALESCE(SUM(bytes_sent), 0) AS bytes_sent,
                       COALESCE(SUM(bytes_recv), 0) AS bytes_recv,
                       COALESCE(SUM(samples), 0) AS samples
                FROM daily_stats
                """
            ).fetchone()
        return dict(row) if row else {"bytes_sent": 0, "bytes_recv": 0, "samples": 0}

    def interface_usage(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT interface,
                       SUM(bytes_sent) AS bytes_sent,
                       SUM(bytes_recv) AS bytes_recv,
                       MAX(upload_peak_bps) AS upload_peak_bps,
                       MAX(download_peak_bps) AS download_peak_bps
                FROM daily_stats
                WHERE date BETWEEN ? AND ?
                GROUP BY interface
                ORDER BY (SUM(bytes_sent) + SUM(bytes_recv)) DESC
                """,
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    # ------------------------------------------------------------------- devices
    def scan_devices(
        self, interface: str, findings: list[dict[str, Any]], ts: int
    ) -> dict[str, int]:
        """Persist a completed discovery scan and return result counters."""
        found = {item["ip"]: item for item in findings}
        created = 0
        with self._connect() as connection:
            connection.execute(
                "UPDATE devices SET is_online = 0 WHERE interface = ?", (interface,)
            )
            for ip, item in found.items():
                existing = connection.execute(
                    "SELECT id FROM devices WHERE ip = ?", (ip,)
                ).fetchone()
                if existing:
                    connection.execute(
                        """
                        UPDATE devices SET mac = COALESCE(?, mac),
                                           hostname = COALESCE(NULLIF(?, ''), hostname),
                                           interface = ?, last_seen = ?, is_online = 1
                        WHERE ip = ?
                        """,
                        (item.get("mac"), item.get("hostname", ""), interface, ts, ip),
                    )
                else:
                    connection.execute(
                        """
                        INSERT INTO devices(ip, mac, hostname, interface, first_seen, last_seen, is_online)
                        VALUES(?, ?, ?, ?, ?, ?, 1)
                        """,
                        (
                            ip,
                            item.get("mac"),
                            item.get("hostname", ""),
                            interface,
                            ts,
                            ts,
                        ),
                    )
                    created += 1

            rows = connection.execute(
                "SELECT id, ip FROM devices WHERE interface = ?", (interface,)
            ).fetchall()
            for row in rows:
                connection.execute(
                    "INSERT INTO device_scans(device_id, ts, online) VALUES(?, ?, ?)",
                    (row["id"], ts, 1 if row["ip"] in found else 0),
                )
        return {"found": len(found), "new": created, "known": len(rows)}

    def list_devices(self) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT id, ip, mac, hostname, interface, first_seen, last_seen, is_online
                FROM devices ORDER BY is_online DESC, last_seen DESC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def device_history(self, device_id: int, limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT ts, online FROM device_scans
                WHERE device_id = ? ORDER BY ts DESC LIMIT ?
                """,
                (device_id, limit),
            ).fetchall()
        return [dict(row) for row in reversed(rows)]

    def devices_discovered_since(self, since_ts: int) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM devices WHERE first_seen >= ?", (since_ts,)
            ).fetchone()
        return int(row["count"]) if row else 0

    def discovery_timeline(self, since_ts: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT (ts / 86400) * 86400 AS day_ts,
                       COUNT(DISTINCT device_id) AS devices
                FROM device_scans
                WHERE ts >= ? AND online = 1
                GROUP BY day_ts ORDER BY day_ts
                """,
                (since_ts,),
            ).fetchall()
        return [dict(row) for row in rows]

    # -------------------------------------------------------------------- alerts
    def create_alert(self, ts: int, alert_type: str, severity: str, message: str) -> dict[str, Any]:
        with self._connect() as connection:
            cursor = connection.execute(
                "INSERT INTO alerts(ts, type, severity, message, acknowledged) VALUES(?, ?, ?, ?, 0)",
                (ts, alert_type, severity, message),
            )
            alert_id = int(cursor.lastrowid)
        return {
            "id": alert_id,
            "ts": ts,
            "type": alert_type,
            "severity": severity,
            "message": message,
            "acknowledged": 0,
        }

    def list_alerts(self, limit: int = 100, unread_only: bool = False) -> list[dict[str, Any]]:
        query = "SELECT id, ts, type, severity, message, acknowledged FROM alerts"
        params: list[Any] = []
        if unread_only:
            query += " WHERE acknowledged = 0"
        query += " ORDER BY ts DESC, id DESC LIMIT ?"
        params.append(limit)
        with self._connect() as connection:
            rows = connection.execute(query, params).fetchall()
        return [dict(row) for row in rows]

    def unread_alert_count(self) -> int:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT COUNT(*) AS count FROM alerts WHERE acknowledged = 0"
            ).fetchone()
        return int(row["count"]) if row else 0

    def alert_summary(self, since_ts: int) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT type, COUNT(*) AS count FROM alerts
                WHERE ts >= ? GROUP BY type ORDER BY count DESC
                """,
                (since_ts,),
            ).fetchall()
        return [dict(row) for row in rows]

    def acknowledge_alert(self, alert_id: int) -> bool:
        with self._connect() as connection:
            cursor = connection.execute(
                "UPDATE alerts SET acknowledged = 1 WHERE id = ?", (alert_id,)
            )
        return cursor.rowcount > 0

    def acknowledge_all_alerts(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("UPDATE alerts SET acknowledged = 1 WHERE acknowledged = 0")
        return cursor.rowcount

    def clear_alerts(self) -> int:
        with self._connect() as connection:
            cursor = connection.execute("DELETE FROM alerts")
        return cursor.rowcount

    # -------------------------------------------------------------- connectivity
    def record_connectivity(
        self, ts: int, online: bool, latency_ms: float | None, method: str | None
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO connectivity_checks(ts, online, latency_ms, method) VALUES(?, ?, ?, ?)",
                (ts, 1 if online else 0, latency_ms, method),
            )

    def connectivity_summary(self, since_ts: int) -> dict[str, Any]:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT COUNT(*) AS total,
                       COALESCE(SUM(online), 0) AS online,
                       AVG(CASE WHEN online = 1 THEN latency_ms END) AS avg_latency_ms
                FROM connectivity_checks WHERE ts >= ?
                """,
                (since_ts,),
            ).fetchone()
        if not row or not row["total"]:
            return {"total": 0, "online": 0, "uptime_percent": None, "avg_latency_ms": None}
        return {
            "total": int(row["total"]),
            "online": int(row["online"]),
            "uptime_percent": round(row["online"] * 100 / row["total"], 1),
            "avg_latency_ms": round(row["avg_latency_ms"], 1) if row["avg_latency_ms"] else None,
        }

    # ------------------------------------------------------------------ retention
    def cleanup(self, retention_days: int) -> dict[str, int]:
        cutoff = int(time.time()) - max(1, retention_days) * 86400
        cutoff_date = (date.today() - timedelta(days=max(1, retention_days))).isoformat()
        with self._connect() as connection:
            samples = connection.execute("DELETE FROM samples WHERE ts < ?", (cutoff,)).rowcount
            daily = connection.execute("DELETE FROM daily_stats WHERE date < ?", (cutoff_date,)).rowcount
            scans = connection.execute("DELETE FROM device_scans WHERE ts < ?", (cutoff,)).rowcount
            alerts = connection.execute("DELETE FROM alerts WHERE ts < ?", (cutoff,)).rowcount
            checks = connection.execute(
                "DELETE FROM connectivity_checks WHERE ts < ?", (cutoff,)
            ).rowcount
        return {
            "samples": samples,
            "daily_stats": daily,
            "device_scans": scans,
            "alerts": alerts,
            "connectivity_checks": checks,
        }

    def database_size(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    def ping(self) -> bool:
        with self._connect() as connection:
            connection.execute("SELECT 1").fetchone()
        return True

    def interface_names(self) -> list[str]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT DISTINCT interface FROM daily_stats ORDER BY interface"
            ).fetchall()
        return [row["interface"] for row in rows]

    def get_device(self, device_id: int) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """
                SELECT id, ip, mac, hostname, interface, first_seen, last_seen, is_online
                FROM devices WHERE id = ?
                """,
                (device_id,),
            ).fetchone()
        return dict(row) if row else None
