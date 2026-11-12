"""NetWatch entry point."""

from __future__ import annotations

import webbrowser
from threading import Timer

from backend.app import create_app
from backend.app.config import HOST, PORT

app = create_app()
socketio = app.extensions["socketio"]


def open_dashboard() -> None:
    webbrowser.open(f"http://{HOST}:{PORT}/")


if __name__ == "__main__":
    print()
    print("  NETWATCH  |  Network Operations Console")
    print(f"  Dashboard: http://{HOST}:{PORT}/")
    print("  Press Ctrl+C to stop.")
    print()
    Timer(1.2, open_dashboard).start()
    socketio.run(
        app,
        host=HOST,
        port=PORT,
        debug=False,
        use_reloader=False,
        allow_unsafe_werkzeug=True,
    )
