"""Shared pytest fixtures for NetWatch."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.app import create_app
from backend.app.db import Database


@pytest.fixture()
def app(tmp_path: Path):
    application = create_app(
        {
            "TESTING": True,
            "START_MONITOR": False,
            "DATABASE": tmp_path / "netwatch-test.db",
            "LOG_FILE": tmp_path / "netwatch-test.log",
        }
    )
    yield application
    monitor = application.extensions.get("monitor")
    if monitor is not None:
        monitor.stop()


@pytest.fixture()
def client(app):
    return app.test_client()


@pytest.fixture()
def database(app) -> Database:
    return app.extensions["db"]
