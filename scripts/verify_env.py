"""NetWatch environment verification.

Run with the project interpreter:
    .\\.venv\\Scripts\\python.exe scripts\\verify_env.py

The script only inspects the environment. It does not start the application,
touch the database, or send network traffic beyond a local port bind test.
"""

from __future__ import annotations

import importlib.metadata as metadata
import ipaddress
import os
import platform
import shutil
import socket
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DATA_DIR = ROOT / "data"
LOG_DIR = ROOT / "logs"

CORE_PACKAGES = [
    "Flask",
    "Flask-SocketIO",
    "simple-websocket",
    "psutil",
    "httpx",
    "dnspython",
]
DEV_PACKAGES = ["pytest"]
WINDOWS_TOOLS = ["ping", "tracert", "arp"]
OPTIONAL_TOOLS = ["git"]
VENDOR_ASSETS = [
    ROOT / "frontend" / "static" / "vendor" / "chart.umd.min.js",
    ROOT / "frontend" / "static" / "vendor" / "socket.io.min.js",
]

results: list[tuple[str, str, str]] = []


def record(status: str, item: str, detail: str) -> None:
    results.append((status, item, detail))


def check_python() -> None:
    version = sys.version_info
    label = f"{version.major}.{version.minor}.{version.micro}"
    if version >= (3, 12):
        note = "" if version[:2] == (3, 12) else " (tested on 3.12)"
        record("OK", "Python", f"{label}{note} at {sys.executable}")
    else:
        record("FAIL", "Python", f"{label} is too old; Python 3.12+ is required")

    if sys.prefix != sys.base_prefix:
        record("OK", "Virtual environment", sys.prefix)
    else:
        record("FAIL", "Virtual environment", "not active; use .venv\\Scripts\\python.exe")

    requirements = ROOT / "requirements.txt"
    record(
        "OK" if requirements.is_file() else "FAIL",
        "Requirements file",
        str(requirements) if requirements.is_file() else "requirements.txt is missing",
    )


def check_packages() -> None:
    for group, names in (("core", CORE_PACKAGES), ("dev", DEV_PACKAGES)):
        for name in names:
            try:
                version = metadata.version(name)
            except metadata.PackageNotFoundError:
                status = "FAIL" if group == "core" else "WARN"
                record(status, f"pip: {name}", "not installed")
            else:
                record("OK", f"pip: {name}", version)


def check_tools() -> None:
    if os.name != "nt":
        record("WARN", "Platform", f"{platform.system()} detected; NetWatch targets Windows 10/11")
    else:
        record("OK", "Platform", f"{platform.system()} {platform.release()}")

    for tool in WINDOWS_TOOLS:
        path = shutil.which(tool)
        record("OK" if path else "FAIL", f"tool: {tool}", path or "not on PATH")
    for tool in OPTIONAL_TOOLS:
        path = shutil.which(tool)
        record("OK" if path else "WARN", f"tool: {tool}", path or "not on PATH (optional)")


def check_writable_directories() -> None:
    for label, directory in (("data", DATA_DIR), ("logs", LOG_DIR)):
        try:
            directory.mkdir(parents=True, exist_ok=True)
            with tempfile.NamedTemporaryFile(dir=directory, delete=True):
                pass
        except OSError as exc:
            record("FAIL", f"{label} directory", f"not writable: {exc}")
        else:
            record("OK", f"{label} directory", str(directory))


def check_vendor_assets() -> None:
    for asset in VENDOR_ASSETS:
        record(
            "OK" if asset.is_file() else "FAIL",
            f"asset: {asset.name}",
            str(asset) if asset.is_file() else "missing vendored frontend asset",
        )


def check_network() -> None:
    try:
        import psutil
    except ImportError:
        return

    addrs = psutil.net_if_addrs()
    stats = psutil.net_if_stats()
    active: list[str] = []
    for name, entries in addrs.items():
        state = stats.get(name)
        if not state or not state.isup:
            continue
        for entry in entries:
            if entry.family != socket.AF_INET or not entry.netmask:
                continue
            try:
                interface = ipaddress.ip_interface(f"{entry.address}/{entry.netmask}")
            except ValueError:
                continue
            if interface.ip.is_loopback or interface.ip.is_link_local:
                continue
            if interface.ip.is_private:
                active.append(f"{name} ({interface.ip})")
    if active:
        record("OK", "Private IPv4 adapter", ", ".join(active))
    else:
        record("WARN", "Private IPv4 adapter", "no active private adapter found")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", 8000))
        except OSError:
            record("WARN", "Port 8000", "in use (expected while NetWatch is running)")
        else:
            record("OK", "Port 8000", "available on 127.0.0.1")


def main() -> int:
    check_python()
    check_packages()
    check_tools()
    check_writable_directories()
    check_vendor_assets()
    check_network()

    width = max(len(item) for _, item, _ in results) + 2
    print("\nNetWatch environment check")
    print("=" * (width + 64))
    for status, item, detail in results:
        print(f"[{status:4}] {item:<{width}} {detail}")
    print("=" * (width + 64))

    failures = sum(status == "FAIL" for status, _, _ in results)
    warnings = sum(status == "WARN" for status, _, _ in results)
    print(f"{len(results)} checks, {failures} failure(s), {warnings} warning(s)")
    if failures:
        print("Resolve the failures above, then run this check again.")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
