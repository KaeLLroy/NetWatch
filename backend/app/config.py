"""Application configuration, defaults, and settings validation."""

from __future__ import annotations

import logging
import os
import re
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any

APP_NAME = "NetWatch"
APP_VERSION = "1.0.0"
BASE_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = BASE_DIR / "data"
LOG_DIR = BASE_DIR / "logs"
DEFAULT_DATABASE = DATA_DIR / "netwatch.db"

HOST = "127.0.0.1"
PORT = int(os.environ.get("NETWATCH_PORT", "8000"))

DEFAULT_SETTINGS: dict[str, Any] = {
    "refresh_interval": 2,
    "interface": "",
    "download_threshold_mbps": 100.0,
    "upload_threshold_mbps": 50.0,
    "retention_days": 30,
    "notifications_enabled": True,
    "public_ip_enabled": True,
    "compact_mode": False,
    "chart_points": 300,
    "internet_check_interval": 15,
    "alert_cooldown_seconds": 300,
    "discovery_timeout_ms": 400,
}

SETTING_TYPES: dict[str, type] = {
    "refresh_interval": int,
    "interface": str,
    "download_threshold_mbps": float,
    "upload_threshold_mbps": float,
    "retention_days": int,
    "notifications_enabled": bool,
    "public_ip_enabled": bool,
    "compact_mode": bool,
    "chart_points": int,
    "internet_check_interval": int,
    "alert_cooldown_seconds": int,
    "discovery_timeout_ms": int,
}

_CONTROL_CHARS = re.compile(r"[\x00-\x1f\x7f]")


class ValidationError(ValueError):
    """Raised when user input fails validation."""


def _number(value: Any, field: str, minimum: float, maximum: float) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValidationError(f"{field} must be a number.")
    number = float(value)
    if not minimum <= number <= maximum:
        raise ValidationError(f"{field} must be between {minimum:g} and {maximum:g}.")
    return number


def _integer(value: Any, field: str, minimum: int, maximum: int) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValidationError(f"{field} must be an integer.")
    if not minimum <= value <= maximum:
        raise ValidationError(f"{field} must be between {minimum} and {maximum}.")
    return value


def validate_settings_payload(payload: Any) -> dict[str, Any]:
    """Validate a partial settings payload and return the cleaned values."""
    if not isinstance(payload, dict):
        raise ValidationError("Settings payload must be a JSON object.")
    unknown = set(payload) - set(DEFAULT_SETTINGS)
    if unknown:
        raise ValidationError(f"Unknown setting(s): {', '.join(sorted(unknown))}.")

    cleaned: dict[str, Any] = {}
    for key, value in payload.items():
        if key == "refresh_interval":
            cleaned[key] = _integer(value, key, 1, 30)
        elif key == "interface":
            if not isinstance(value, str):
                raise ValidationError("interface must be a string.")
            interface = value.strip()
            if len(interface) > 128 or _CONTROL_CHARS.search(interface):
                raise ValidationError("interface name is invalid.")
            cleaned[key] = interface
        elif key in {"download_threshold_mbps", "upload_threshold_mbps"}:
            cleaned[key] = round(_number(value, key, 0, 100_000), 2)
        elif key == "retention_days":
            cleaned[key] = _integer(value, key, 1, 365)
        elif key in {"notifications_enabled", "public_ip_enabled", "compact_mode"}:
            if not isinstance(value, bool):
                raise ValidationError(f"{key} must be true or false.")
            cleaned[key] = value
        elif key == "chart_points":
            cleaned[key] = _integer(value, key, 20, 300)
        elif key == "internet_check_interval":
            cleaned[key] = _integer(value, key, 5, 300)
        elif key == "alert_cooldown_seconds":
            cleaned[key] = _integer(value, key, 30, 3600)
        elif key == "discovery_timeout_ms":
            cleaned[key] = _integer(value, key, 100, 2000)
    return cleaned


def configure_logging(level: int = logging.INFO) -> None:
    """Configure rotating file logging plus a concise console handler."""
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    root = logging.getLogger()
    if any(isinstance(handler, RotatingFileHandler) for handler in root.handlers):
        return

    root.setLevel(level)
    formatter = logging.Formatter(
        "%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    file_handler = RotatingFileHandler(
        LOG_DIR / "netwatch.log", maxBytes=2_000_000, backupCount=4, encoding="utf-8"
    )
    file_handler.setFormatter(formatter)
    console = logging.StreamHandler()
    console.setFormatter(formatter)
    root.addHandler(file_handler)
    root.addHandler(console)
