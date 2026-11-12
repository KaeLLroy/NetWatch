"""Alert creation, deduplication, and realtime notification delivery."""

from __future__ import annotations

import threading
import time
from typing import Any

from flask import Flask

from ..db import Database


class AlertService:
    """Persist alerts and push them to connected dashboards."""

    def __init__(self, database: Database, socketio: Any, app: Flask) -> None:
        self.database = database
        self.socketio = socketio
        self.app = app
        self._lock = threading.Lock()
        self._last_triggered: dict[str, float] = {}

    def trigger(
        self,
        alert_type: str,
        severity: str,
        message: str,
        *,
        dedupe_seconds: int | None = None,
        now: int | None = None,
    ) -> dict[str, Any] | None:
        """Create an alert unless the same type fired inside its cooldown."""
        timestamp = int(time.time()) if now is None else int(now)
        if dedupe_seconds is None:
            dedupe_seconds = int(self.database.get_settings()["alert_cooldown_seconds"])

        with self._lock:
            last = self._last_triggered.get(alert_type, 0)
            if dedupe_seconds > 0 and timestamp - last < dedupe_seconds:
                return None
            self._last_triggered[alert_type] = timestamp

        record = self.database.create_alert(timestamp, alert_type, severity, message)
        if self.socketio is not None:
            try:
                with self.app.app_context():
                    self.socketio.emit("alert", record)
            except Exception:  # noqa: BLE001 - a socket failure must not stop monitoring
                self.app.logger.exception("Unable to emit alert event")
        return record
