# NetWatch

**A local network observability and diagnostics console for Windows.**

NetWatch brings Windows adapter counters, TCP session tables, connectivity probes,
DNS lookups, and authorized private-LAN discovery into one operational interface. It is
built with Flask, SQLite, and vanilla JavaScript, uses real telemetry only, and runs
entirely on `127.0.0.1`.

The project was developed as a university admission portfolio piece and as a practical
homelab tool. The goal was not to wrap a dashboard around random data, but to make real
Windows network state legible without packet capture, cloud services, or a build toolchain.

---

## Contents

- [Why NetWatch exists](#why-netwatch-exists)
- [What it does](#what-it-does)
- [Design approach](#design-approach)
- [Screenshots](#screenshots)
- [Technology stack](#technology-stack)
- [Architecture](#architecture)
- [How monitoring works](#how-monitoring-works)
- [Data and retention](#data-and-retention)
- [Windows setup](#windows-setup)
- [Development](#development)
- [Configuration](#configuration)
- [API overview](#api-overview)
- [Security and privacy](#security-and-privacy)
- [Testing and verification](#testing-and-verification)
- [Limitations](#limitations)
- [Future work](#future-work)
- [Educational context](#educational-context)

---

## Why NetWatch exists

A Windows machine exposes network state through several disconnected tools. Task Manager
shows one aggregate throughput number. `ipconfig` lists adapters. `netstat` lists sockets.
`ping`, `tracert`, `nslookup`, and `arp` answer individual questions with different output
formats. None of them provide a persistent, correlated view.

NetWatch joins those sources into a single local console:

- throughput history and daily totals are stored, not just displayed for a moment;
- adapters, sessions, devices, alerts, and diagnostics share one interface;
- the data is real and reproducible, with no seeded demo records;
- the application remains safe for a single user on a local machine.

The project is deliberately scoped. It monitors the machine it runs on. It does not
capture packets, scan ports, store browsing content, or attempt to be a multi-user
network management platform.

## What it does

### Network overview

Live download and upload rates, today and lifetime transfer totals, the monitored adapter,
link speed, MAC and local address, optional public egress IP, internet reachability and
latency, system uptime, recent alerts, and a live Chart.js area chart. Updates arrive over
Socket.IO with a REST fallback poll.

### Interfaces

Every adapter Windows reports, classified as Wi-Fi, Ethernet, virtual, VPN, or loopback.
Each card shows addresses, MAC, MTU, duplex, link speed, operational state, byte and packet
counters, errors, and drops. The monitored adapter can be selected explicitly; otherwise
NetWatch follows the Windows default route and falls back to the busiest active adapter.

### Traffic analysis

Server-side aggregates for 1 hour, 6 hours, 24 hours, 7 days, and 30 days. Each range
shows transfer totals, peak upload and download rates, a rate chart, and daily history.
Daily aggregates can be exported as CSV.

### Connected devices

An explicitly authorized discovery scan combines a single ICMP echo per host with the
Windows neighbor cache and reverse DNS. Scans are limited to the selected adapter's private
IPv4 subnet and capped at `/24`. Results are stored as a device inventory with first seen,
last seen, online state, MAC, hostname, and per-device scan history. Progress is streamed
to the page while the scan runs.

### Active connections

A live TCP table with local and remote endpoints, connection state, owning process, and
PID. Includes state counts, a state filter, and free-text search. When Windows denies access
to process attribution, the interface says so instead of displaying misleading blanks.

### Diagnostics

- **Ping:** four ICMP echo requests with loss, minimum, maximum, and average latency.
- **DNS:** A, AAAA, CNAME, MX, NS, and TXT lookups through the system resolver.
- **Traceroute:** up to 20 hops with reverse lookup disabled.
- **Connectivity:** independent TCP and DNS checks with per-target latency.

Targets are validated as literal IP addresses or strict RFC-1123 hostnames before a fixed
argument array is executed. Commands run without a shell, with bounded output and hard
timeouts.

### Historical analytics

Seven, 30, or 90-day trends for bandwidth, transfer totals, daily usage, interface usage,
alert distribution, connectivity uptime, and discovery activity. Includes a bandwidth
chart, daily bar chart, uptime doughnut, interface breakdown, alert breakdown, and daily
table.

### Alert center

Alerts for internet transitions, interface availability, and configurable download and
upload thresholds. Alerts have severities, cooldowns, unread state, filtering,
acknowledgement, and confirmed history clearing. New alerts are persisted and pushed to
open dashboards.

### Settings

Refresh cadence, monitored adapter, chart window, public-IP lookup, compact mode, alert
thresholds, cooldown, notifications, retention period, and discovery timeout. Values are
validated on the server, stored in SQLite, and applied to the monitoring engine
immediately.

## Design approach

The interface uses a restrained network-operations-console visual language: charcoal and
slate surfaces, a single cyan accent, compact typography, flat borders, and small corner
radii. Green, amber, and red are reserved for operational state rather than decoration.
Charts use cyan for download and slate-blue for upload so status colors keep their meaning.

The redesign replaced the visual system without changing the backend, template IDs, data
attributes, JavaScript selectors, or API contracts. Tables scroll horizontally at narrow
widths instead of squeezing columns into illegibility, and the navigation collapses into a
drawer on small screens.

## Screenshots

No screenshots are published in this repository. A live NetWatch capture necessarily
contains the operator's hostname, adapter names, private addresses, MAC addresses, and
possibly public egress IP and process names. Authentic captures are deliberately excluded
from version control. See [docs/SCREENSHOTS.md](docs/SCREENSHOTS.md) for the publication
policy and safe-capture guidance.

This README describes the interface and behavior without presenting unredacted network
data as marketing material.

## Technology stack

| Layer | Technology |
|---|---|
| Runtime | Python 3.12+ (tested on Python 3.12.10, Windows 11) |
| Web application | Flask 3.1 |
| Realtime | Flask-SocketIO 5.7 in `threading` mode, vendored Socket.IO client |
| Telemetry | psutil, Windows `ping` / `tracert` / `arp`, dnspython, httpx |
| Storage | SQLite through the Python standard library, WAL mode |
| Frontend | HTML5, CSS3, vanilla JavaScript, vendored Chart.js 4 |
| Quality | pytest, Ruff, compileall, custom environment verifier |
| Packaging | `setup.bat`, `start.bat`, `requirements.txt` |

No Node.js, npm, Vite, React, database server, or administrator account is required for
normal monitoring. Elevation only improves process-name attribution in the TCP table.

## Architecture

```text
Browser: HTML, CSS, vanilla JS, Chart.js
   │  REST /api/*                         Socket.IO: telemetry, alerts, scan progress
   ▼
Flask application factory
   ├─ security headers, trusted hosts, JSON mutation guard, API envelopes
   ├─ NetworkMonitor thread ── psutil counters, connectivity, public IP,
   │                           threshold alerts, retention cleanup
   ├─ DiscoveryService thread ─ ICMP sweep, ARP cache, reverse DNS
   ├─ AlertService ─────────── cooldowns, persistence, realtime delivery
   ├─ Diagnostics services ─── validated ping, DNS, traceroute, connectivity
   └─ Database ─────────────── SQLite: settings, samples, aggregates, devices,
                               scan history, alerts, connectivity checks
```

The Flask process owns one background sampling thread and one short-lived discovery thread.
SQLite keeps the local state durable across restarts. Socket.IO pushes updates to the
browser; ordinary REST requests remain the source of truth and the fallback path.

Detailed design notes, process boundaries, data flow, and failure handling are in
[ARCHITECTURE.md](ARCHITECTURE.md). The networking methods and their limits are documented
in [NETWORKING.md](NETWORKING.md).

## How monitoring works

1. **Sample adapter counters.** Every `refresh_interval` seconds, NetWatch reads cumulative
   byte and packet counters from `psutil.net_io_counters(pernic=True)` and link state from
   `psutil.net_if_stats()`.
2. **Convert counters to rates.** Deltas are divided by elapsed time measured with
   `time.monotonic()`, then multiplied by eight to produce bits per second. Negative deltas
   are treated as adapter resets rather than impossible negative traffic.
3. **Reject implausible deltas.** A delta is discarded when bytes move without packets, the
   implied frame size exceeds 65,535 bytes, or the implied throughput exceeds 1.5 times the
   negotiated link speed. This guards against known Windows wireless-driver counter
   glitches.
4. **Persist and aggregate.** Each accepted sample is written to `samples` and upserted into
   `daily_stats` in the same transaction. The live chart receives the sample over Socket.IO.
5. **Check connectivity.** Every 15 seconds by default, NetWatch attempts TCP handshakes to
   three public DNS resolvers on port 53, with the Windows NCSI endpoint as a fallback. The
   fastest successful probe supplies the reported latency.
6. **Look up public IP only when enabled.** Independent HTTPS providers are queried at most
   once every ten minutes. This is the only optional outbound data source.
7. **Evaluate alerts.** Threshold crossings require a fresh rise above the configured rate;
   they reset after traffic falls below 80% of the threshold. Interface and internet
   transitions trigger immediately, subject to the alert cooldown.

Discovery and diagnostics are user-initiated. Discovery never leaves the selected private
IPv4 subnet and never probes ports. Diagnostics validate the target before invoking the
fixed Windows tool.

## Data and retention

All state lives in `data/netwatch.db`:

| Table | Purpose |
|---|---|
| `settings` | JSON-encoded user preferences |
| `samples` | Per-interval byte deltas, upload rate, download rate |
| `daily_stats` | Per-day, per-interface totals and peaks |
| `devices` | Latest device inventory and online state |
| `device_scans` | Per-device online/offline observations |
| `alerts` | Severity, message, timestamp, acknowledgement |
| `connectivity_checks` | Internet state, latency, and probe method |

SQLite runs in WAL mode with a 15-second busy timeout. Each operation uses its own
connection, which keeps the sampling thread, request threads, and discovery thread from
sharing a connection object.

Retention defaults to 30 days and can be set from 1 to 365. Cleanup runs at startup and
hourly. It removes old raw samples, daily aggregates, device scan history, alerts, and
connectivity checks. The current device inventory is retained until the database is reset.

The database is safe to delete while NetWatch is stopped; it is recreated with defaults on
the next launch. Logs rotate at 2 MB with four backups.

## Windows setup

### Requirements

- Windows 10 or Windows 11.
- Python **3.12 or newer** with `python.exe` on `PATH`, or the `py -3.12` launcher.
- An active network adapter for live telemetry.
- No Node.js, database server, or administrator rights required.

### One-command setup

Double-click **`setup.bat`**, or run it from a terminal:

```bat
setup.bat
```

The script selects a compatible Python interpreter, creates `.venv`, installs the runtime
dependencies, creates `data/` and `logs/`, and runs `scripts\verify_env.py`.

### Start

Double-click **`start.bat`**, or run:

```bat
start.bat
```

NetWatch starts at **http://127.0.0.1:8000/** and opens the dashboard in the default
browser. Press `Ctrl+C` in the terminal to stop it. If `.venv` is missing, `start.bat`
invokes setup first.

### Manual setup

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe scripts\verify_env.py
.\.venv\Scripts\python.exe run.py
```

Calling `.\.venv\Scripts\python.exe` directly is the supported workflow. Activation is
optional; PowerShell execution policy does not need to be changed.

### Environment variables

| Variable | Default | Purpose |
|---|---|---|
| `NETWATCH_PORT` | `8000` | Local HTTP port |
| `NETWATCH_SECRET_KEY` | Random per launch | Flask session signing key |

The bind address is fixed to `127.0.0.1` in `backend/app/config.py`. NetWatch has no option
to listen on the LAN.

If port 8000 is occupied:

```bat
set NETWATCH_PORT=8010
start.bat
```

Then open `http://127.0.0.1:8010/`.

## Development

### Project layout

```text
NetWatch/
├─ run.py                        Entry point; starts Flask-SocketIO on 127.0.0.1
├─ setup.bat / start.bat         Windows setup and launch flow
├─ requirements.txt              Runtime dependencies
├─ requirements-dev.txt          Test, lint, and type tooling
├─ pyproject.toml                Pytest and Ruff configuration
├─ backend/app/
│  ├─ __init__.py                Application factory, Socket.IO, security headers
│  ├─ config.py                  Defaults, validation, logging
│  ├─ db.py                      Schema, repository, aggregation, retention
│  ├─ metrics.py                 Rate calculation and counter plausibility checks
│  ├─ monitoring.py              Sampling, connectivity, alert evaluation
│  ├─ routes/api.py              REST API and error envelopes
│  ├─ routes/views.py            Nine HTML page routes
│  └─ services/                  Alerts, connections, connectivity, diagnostics,
│                                discovery, interfaces
├─ frontend/
│  ├─ templates/                 Base layout, nine pages, error pages
│  └─ static/
│     ├─ css/styles.css          NOC design system
│     ├─ js/                     Shared runtime and page controllers
│     ├─ img/favicon.png         Browser tab icon
│     ├─ img/brand-mark.png      Sidebar and About mark
│     └─ vendor/                 Chart.js and Socket.IO
├─ tests/                        96 pytest tests
├─ scripts/verify_env.py         Dependency, tool, asset, and adapter check
├─ docs/SCREENSHOTS.md           Screenshot publication policy
├─ data/                         SQLite database (git-ignored)
└─ logs/                         Rotating log (git-ignored)
```

### Install development tools

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
```

### Test

```powershell
.\.venv\Scripts\python.exe -m pytest -q
```

The suite uses temporary SQLite databases and disables the background monitor. It does not
touch `data/netwatch.db` and does not send ICMP probes. Platform-dependent command output
is supplied through fixtures rather than executed.

### Lint and compile

```powershell
.\.venv\Scripts\python.exe -m ruff check backend tests scripts
.\.venv\Scripts\python.exe -m compileall -q backend tests run.py
```

### Verify the environment

```powershell
.\.venv\Scripts\python.exe scripts\verify_env.py
```

The verifier checks the Python version, virtual environment, packages, Windows tools,
writable runtime directories, vendored frontend assets, an active private adapter, and
whether port 8000 is available. A running NetWatch instance produces a port warning rather
than a failure.

### Development workflow

- CSS and JavaScript are served from disk; browser refresh is enough after static edits.
- Python and template changes require a process restart. Flask runs with `debug=False` and
  `use_reloader=False` to avoid starting duplicate monitoring threads.
- Logs are written to `logs/netwatch.log` and to the terminal.
- To reset all persisted state, stop NetWatch and delete `data/netwatch.db`. The database is
  recreated on the next start.

## Configuration

Defaults are stored in `backend/app/config.py` and can be changed in the Settings page:

| Setting | Default | Accepted range |
|---|---|---|
| Refresh interval | 2 seconds | 1–30 |
| Monitored interface | Automatic | Any detected adapter |
| Live chart window | 300 samples | 20–300 |
| Download alert threshold | 100 Mbps | 0–100,000 (0 disables) |
| Upload alert threshold | 50 Mbps | 0–100,000 (0 disables) |
| Alert cooldown | 300 seconds | 30–3,600 |
| Retention | 30 days | 1–365 |
| Discovery timeout | 400 ms | 100–2,000 |
| Connectivity check interval | 15 seconds | 5–300 |
| Public IP lookup | Enabled | On/off |
| In-app notifications | Enabled | On/off |
| Compact mode | Disabled | On/off |

Unknown setting keys and out-of-range values are rejected. Changes are persisted and the
monitor is woken immediately to apply them.

## API overview

All API responses use a consistent envelope:

```json
{ "ok": true, "data": {} }
{ "ok": false, "error": "Human-readable reason." }
```

| Method | Endpoint | Purpose |
|---|---|---|
| GET | `/api/health` | Database and monitor health |
| GET | `/api/system/info` | Version, host, runtime, paths, monitor state |
| GET | `/api/dashboard/summary` | Live snapshot, totals, interface data, alerts |
| GET | `/api/interfaces` | Adapter inventory and selection state |
| POST | `/api/interfaces/select` | Persist the monitored adapter |
| GET | `/api/traffic/history?range=24h` | Bucketed traffic history |
| GET | `/api/traffic/live?points=60` | Recent raw samples |
| GET | `/api/traffic/daily?days=14` | Daily aggregates |
| GET | `/api/traffic/summary` | Today, week, month, and lifetime totals |
| GET | `/api/traffic/export.csv?days=30` | CSV download |
| GET | `/api/connections?state=ESTABLISHED` | Active TCP sessions |
| GET | `/api/devices` | Inventory and scan state |
| POST | `/api/devices/scan` | Start discovery (`{"confirm": true}`) |
| GET | `/api/devices/scan/status` | Discovery progress |
| GET | `/api/devices/<id>/history` | Per-device scan history |
| POST | `/api/diagnostics/ping` | Validated ICMP ping |
| POST | `/api/diagnostics/dns` | Validated DNS lookup |
| POST | `/api/diagnostics/traceroute` | Validated traceroute |
| GET | `/api/diagnostics/connectivity` | Multi-target reachability |
| GET | `/api/analytics/overview?days=7` | Historical summary |
| GET | `/api/analytics/bandwidth?days=30` | Hourly bandwidth and daily totals |
| GET | `/api/analytics/devices?days=30` | Discovery timeline |
| GET | `/api/alerts?limit=100&unread=true` | Alert history |
| POST | `/api/alerts/<id>/ack` | Acknowledge one alert |
| POST | `/api/alerts/ack-all` | Acknowledge all unread alerts |
| POST | `/api/alerts/clear` | Clear alert history |
| GET / PUT | `/api/settings` | Read or update validated settings |
| POST | `/api/settings/reset` | Restore defaults |

Traffic ranges are `1h`, `6h`, `24h`, `7d`, and `30d`. Mutation requests must use
`application/json` and pass the same-origin checks. Diagnostic endpoints are rate-limited
per client address.

## Security and privacy

NetWatch is a local, single-user console. Its threat model assumes the operator controls
the machine and the browser session.

- **Localhost binding.** The server binds `127.0.0.1`; Flask trusted hosts accept only
  `127.0.0.1`, `localhost`, and loopback IPv6 forms.
- **No shell execution.** Diagnostics and discovery pass validated arguments to fixed
  command arrays. Targets are never interpolated into a shell string.
- **Validated input.** Settings are type- and range-checked; unknown keys are rejected.
  Hostnames must match a strict RFC-1123 pattern and IP literals are parsed with
  `ipaddress`.
- **Request hardening.** Mutations require JSON, reject cross-site `Origin` and
  `Sec-Fetch-Site` values, and are capped at 256 KB.
- **Browser hardening.** A restrictive Content Security Policy blocks remote and inline
  scripts and framing; MIME sniffing, referrers, and sensitive browser permissions are
  restricted.
- **No packet capture.** NetWatch reads counters, socket metadata, and command output. It
  never captures or stores packet payloads, credentials, or browsing content.
- **Authorized discovery only.** Scans require explicit confirmation, stay inside the
  selected private IPv4 subnet, are capped at `/24`, and perform only ICMP echo, ARP cache
  reads, and reverse DNS.
- **Local persistence.** Traffic aggregates, settings, devices, scan history, and alerts
  stay in `data/netwatch.db`. Public-IP lookup is optional and uses independent HTTPS
  providers only while enabled.
- **Log hygiene.** Logs contain application events and errors, not credentials or packet
  contents.

There is no authentication layer because the service is not reachable from other machines.
Do not expose NetWatch through a public interface or reverse proxy without adding
authentication, TLS, and a production WSGI server.

> Only scan networks you own or have explicit permission to assess. Discovery requires a
> confirmation checkbox in the UI and `{"confirm": true}` in the API request.

## Testing and verification

Current status:

- **96 pytest tests pass.**
- **Ruff passes** for `backend`, `tests`, and `scripts`.
- **`compileall` passes** for the backend, tests, and entry point.
- **Environment verification passes** with no failures; warnings are expected when port
  8000 is occupied or optional tools such as Git or pytest are absent.
- **UI audit:** all nine pages loaded at 1600×1000 and 390×844 through Chrome DevTools
  Protocol with zero console errors, zero page-level horizontal overflow, and no unstyled
  rendered classes. No screenshots were captured during the audit.

The test suite covers:

- rate conversion, counter resets, impossible frame sizes, and link-speed bounds;
- settings and target validation, MAC normalization, and safe subnet derivation;
- SQLite settings, samples, daily aggregation, devices, alerts, connectivity, and retention;
- Windows ping and traceroute parsing, including replies without a summary block;
- DNS formatting and error handling;
- alert cooldowns, persistence, defaults, and realtime emission;
- every page and API area, error envelopes, query validation, device history, scan
  confirmation, CSV export, diagnostics safety, and same-origin/JSON guards.

## Limitations

- **Windows-first.** psutil and the diagnostics have portable foundations, but the supported
  environment is Windows 10/11. Command names and localized output differ elsewhere.
- **Single host.** NetWatch observes the machine it runs on. It is not a distributed
  monitoring system.
- **Local single-user design.** There are no accounts, roles, TLS, or remote-access
  features. The development Flask-SocketIO server is appropriate for local use only.
- **SQLite.** One local writer and a moderate retention window are deliberate. A long-term
  multi-host deployment would need a time-series store and partitioned retention.
- **IPv4 discovery only.** Discovery uses the selected adapter's private IPv4 subnet and
  does not enumerate IPv6 neighbors.
- **ICMP depends on the network.** Windows Firewall, client isolation, or disabled ICMP
  replies can hide hosts that still appear in the ARP cache or not at all.
- **Diagnostic parsing favors English output.** Raw ping and traceroute output is always
  shown, but non-English Windows installations may produce fewer parsed fields.
- **Process attribution can be restricted.** Protected Windows services may hide their
  owning process unless NetWatch runs elevated.
- **Public IP is external.** The optional lookup contacts third-party HTTPS providers and
  can fail independently of local connectivity.
- **No packet inspection.** NetWatch intentionally does not capture payloads or fingerprint
  services.
- **Screenshots are not published.** Authentic captures contain host-specific identifiers;
  see the policy note instead.

## Future work

- Add an optional authenticated remote mode with TLS and a production WSGI server.
- Introduce lightweight agents and a time-series backend for multi-host monitoring.
- Add IPv6 neighbor discovery and configurable discovery scopes.
- Support additional alert delivery channels and per-alert mute rules.
- Add richer reporting and scheduled exports.
- Add automated browser tests that assert behavior without producing image artifacts.
- Package a signed installer only if it can preserve the transparent, source-first setup
  flow.

## Educational context

NetWatch was built to demonstrate practical networking, backend engineering, security
awareness, data persistence, testing, and interface design in one coherent system. It is
intended for authorized, local network observation and learning.

Third-party components include Flask, Flask-SocketIO, simple-websocket, psutil, dnspython,
httpx, Chart.js, and Socket.IO. Their respective licenses apply.
