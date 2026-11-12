"""NetWatch Flask application factory."""

from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from flask import Flask, jsonify, render_template, request
from flask_socketio import SocketIO, emit

from .config import (
    APP_NAME,
    APP_VERSION,
    BASE_DIR,
    DEFAULT_DATABASE,
    HOST,
    LOG_DIR,
    PORT,
    ValidationError,
    configure_logging,
)
from .db import Database
from .monitoring import NetworkMonitor
from .routes.api import api, fail
from .routes.views import views
from .services.alerts import AlertService
from .services.discovery import DiscoveryService


def create_app(config_overrides: dict | None = None) -> Flask:
    app = Flask(
        __name__,
        template_folder=str(BASE_DIR / "frontend" / "templates"),
        static_folder=str(BASE_DIR / "frontend" / "static"),
        static_url_path="/static",
    )
    app.config.from_mapping(
        SECRET_KEY=os.environ.get("NETWATCH_SECRET_KEY") or secrets.token_hex(32),
        DATABASE=DEFAULT_DATABASE,
        LOG_FILE=LOG_DIR / "netwatch.log",
        START_MONITOR=True,
        MAX_CONTENT_LENGTH=256 * 1024,
        JSON_SORT_KEYS=False,
        TRUSTED_HOSTS=["127.0.0.1", "localhost", "::1", "[::1]"],
        SEND_FILE_MAX_AGE_DEFAULT=0,
        TESTING=False,
    )
    if config_overrides:
        app.config.update(config_overrides)

    app.config["DATABASE"] = Path(app.config["DATABASE"])
    app.config["LOG_FILE"] = Path(app.config["LOG_FILE"])
    if not app.config["TESTING"]:
        configure_logging()

    database = Database(app.config["DATABASE"])
    database.initialize()
    app.extensions["db"] = database

    socketio = SocketIO(
        app,
        async_mode="threading",
        cors_allowed_origins=[],
        logger=False,
        engineio_logger=False,
    )
    app.extensions["socketio"] = socketio

    alert_service = AlertService(database, socketio, app)
    app.extensions["alerts"] = alert_service

    monitor = NetworkMonitor(app, socketio, database, alert_service)
    app.extensions["monitor"] = monitor

    discovery = DiscoveryService(app, socketio, database)
    app.extensions["discovery"] = discovery

    app.register_blueprint(views)
    app.register_blueprint(api)

    @socketio.on("connect")
    def handle_connect():
        emit(
            "monitor_status",
            {
                "running": monitor.snapshot()["monitor_running"],
                "server_time": int(time.time()),
            },
        )

    @app.after_request
    def security_headers(response):
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "no-referrer")
        response.headers.setdefault(
            "Permissions-Policy", "camera=(), microphone=(), geolocation=(), payment=()"
        )
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault(
            "Content-Security-Policy",
            "default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; "
            "img-src 'self' data:; connect-src 'self' ws: wss:; font-src 'self'; "
            "object-src 'none'; base-uri 'self'; frame-ancestors 'none'",
        )
        if request.path.startswith("/api/"):
            response.headers.setdefault("Cache-Control", "no-store")
        return response

    @app.context_processor
    def inject_globals():
        return {
            "app_name": APP_NAME,
            "app_version": APP_VERSION,
            "current_year": time.gmtime().tm_year,
        }

    @app.errorhandler(404)
    def not_found(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "API endpoint not found."}), 404
        return render_template("404.html", page_title="Page not found", active_page=""), 404

    @app.errorhandler(413)
    def payload_too_large(_error):
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Request body is too large."}), 413
        return render_template("404.html", page_title="Request too large", active_page=""), 413

    @app.errorhandler(500)
    def internal_error(error):
        app.logger.error("Unhandled application error: %s", error)
        if request.path.startswith("/api/"):
            return jsonify({"ok": False, "error": "Internal server error."}), 500
        return render_template("500.html", page_title="Server error", active_page=""), 500

    @app.errorhandler(ValidationError)
    def validation_error(error):
        if request.path.startswith("/api/"):
            return fail(str(error), 400)
        return render_template("404.html", page_title="Invalid request", active_page=""), 400

    settings = database.get_settings()
    database.cleanup(int(settings["retention_days"]))
    app.extensions["started_at"] = int(time.time())

    if app.config.get("START_MONITOR"):
        monitor.start()
        app.logger.info(
            "%s %s started on http://%s:%s (database=%s)",
            APP_NAME,
            APP_VERSION,
            HOST,
            PORT,
            app.config["DATABASE"],
        )
    return app
