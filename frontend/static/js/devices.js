/* Devices — authorized local discovery and device history. */
(function () {
  "use strict";
  const NW = window.NW;

  let devices = [];
  let filter = "";
  let pollTimer = null;
  let historyChart = null;

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  function renderTable() {
    const body = document.getElementById("device-table-body");
    if (!body) return;
    const query = filter.trim().toLowerCase();
    const rows = devices.filter((device) =>
      [device.ip, device.mac, device.hostname, device.interface].some((value) =>
        String(value || "").toLowerCase().includes(query)
      )
    );
    setText("device-table-subtitle", `${rows.length} of ${devices.length} recorded devices`);
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="8" class="table-empty">${
        devices.length ? "No devices match this search." : "No devices discovered yet. Run an authorized scan to build the inventory."
      }</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map(
        (device) => `<tr>
          <td><span class="status-inline" data-state="${device.is_online ? "online" : "checking"}"><span class="status-dot"></span>${device.is_online ? "Online" : "Offline"}</span></td>
          <td class="mono">${NW.escape(device.ip)}</td>
          <td class="mono">${NW.escape(device.mac || "—")}</td>
          <td>${NW.escape(device.hostname || "—")}</td>
          <td>${NW.escape(device.interface || "—")}</td>
          <td>${NW.relative(device.first_seen)}</td>
          <td>${NW.relative(device.last_seen)}</td>
          <td><div class="device-actions"><button class="table-action" type="button" data-history="${device.id}" aria-label="View device history" title="View scan history">${NW.icon("clock")}</button></div></td>
        </tr>`
      )
      .join("");
    body.querySelectorAll("[data-history]").forEach((button) => {
      button.addEventListener("click", () => openHistory(Number(button.dataset.history)));
    });
  }

  function renderSummary(data) {
    devices = data.devices || [];
    setText("devices-known", data.count ?? devices.length);
    setText("devices-online", data.online ?? 0);
    const last = data.last_scan;
    setText("devices-last-scan", last ? NW.relative(last) : "Never");
    setText("devices-last-scan-abs", last ? NW.dateTime(last) : "No scan recorded");
    const scan = data.scan || {};
    setText("devices-network", scan.network || "Not scanned");
    setText("devices-interface", scan.interface || data.devices?.[0]?.interface || "Selected adapter");
    setText("scan-target-network", scan.network || "the selected adapter's private IPv4 subnet");
    renderTable();
  }

  async function load(showToast = false) {
    try {
      const data = await NW.api("/api/devices");
      renderSummary(data);
      const start = document.getElementById("open-scan-dialog");
      if (data.scan?.running) {
        showProgress(data.scan);
        if (start) start.disabled = true;
        if (!pollTimer) pollStatus();
      } else if (start) {
        start.disabled = false;
      }
      if (showToast) NW.toast("Device inventory refreshed.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to load devices");
    }
  }

  function showProgress(state) {
    const card = document.getElementById("scan-progress-card");
    if (!card) return;
    card.hidden = false;
    const phaseLabels = {
      scanning: "Scanning local subnet…",
      resolving: "Resolving hostnames…",
      saving: "Saving discovery results…",
      done: "Discovery complete",
      error: "Discovery failed",
    };
    setText("scan-phase", phaseLabels[state.phase] || "Scanning…");
    const total = state.total || 1;
    setText(
      "scan-detail",
      state.phase === "done"
        ? `${state.result?.found ?? 0} devices found · ${state.result?.new ?? 0} new`
        : `${state.progress || 0} / ${total} hosts checked · ${state.network || ""}`
    );
    const bar = document.getElementById("scan-progress-bar");
    if (bar) bar.style.width = `${Math.min(100, state.percent || 0)}%`;
  }

  function hideProgress() {
    const card = document.getElementById("scan-progress-card");
    if (card) card.hidden = true;
  }

  async function pollStatus() {
    try {
      const state = await NW.api("/api/devices/scan/status");
      showProgress(state);
      if (state.running) {
        pollTimer = setTimeout(pollStatus, 800);
      } else {
        pollTimer = null;
        const start = document.getElementById("open-scan-dialog");
        if (start) start.disabled = false;
        if (state.phase === "done") {
          const result = state.result || {};
          NW.toast(
            `${result.found ?? 0} devices found, ${result.new ?? 0} new. Scan completed in ${((result.scan_duration_ms || 0) / 1000).toFixed(1)}s.`,
            "success",
            "Discovery complete"
          );
          await load();
          setTimeout(hideProgress, 2200);
        } else if (state.phase === "error") {
          NW.toast(state.error || "Discovery failed.", "error", "Scan failed");
          setTimeout(hideProgress, 2500);
        }
      }
    } catch (error) {
      pollTimer = null;
      NW.toast(error.message, "error", "Unable to read scan status");
    }
  }

  async function startScan() {
    const consent = document.getElementById("scan-consent");
    if (!consent?.checked) return;
    const dialog = document.getElementById("device-scan-dialog");
    if (dialog?.open) dialog.close();
    const start = document.getElementById("open-scan-dialog");
    if (start) start.disabled = true;
    try {
      const state = await NW.api("/api/devices/scan", { method: "POST", body: { confirm: true } });
      showProgress(state);
      pollStatus();
    } catch (error) {
      if (start) start.disabled = false;
      NW.toast(error.message, "error", "Unable to start discovery");
    }
  }

  async function openHistory(deviceId) {
    const dialog = document.getElementById("device-history-dialog");
    const body = document.getElementById("device-history-body");
    if (!dialog || !body) return;
    body.innerHTML = `<tr><td colspan="2" class="table-empty">Loading device history…</td></tr>`;
    dialog.showModal();
    try {
      const data = await NW.api(`/api/devices/${deviceId}/history`);
      setText("history-dialog-title", data.device.hostname || data.device.ip);
      setText(
        "history-device-meta",
        `${data.device.ip} · ${data.device.mac || "No MAC"} · ${data.device.interface || "Unknown interface"}`
      );
      const history = data.history || [];
      body.innerHTML = history.length
        ? history
            .slice()
            .reverse()
            .map(
              (entry) => `<tr><td>${NW.dateTime(entry.ts)}</td><td><span class="status-inline" data-state="${entry.online ? "online" : "checking"}"><span class="status-dot"></span>${entry.online ? "Online" : "Offline"}</span></td></tr>`
            )
            .join("")
        : `<tr><td colspan="2" class="table-empty">No scan history recorded for this device.</td></tr>`;
      drawHistory(history);
    } catch (error) {
      body.innerHTML = `<tr><td colspan="2" class="table-empty">${NW.escape(error.message)}</td></tr>`;
      NW.toast(error.message, "error", "Unable to load device history");
    }
  }

  function drawHistory(history) {
    const canvas = document.getElementById("device-history-chart");
    if (!canvas || typeof Chart !== "function") return;
    if (historyChart) historyChart.destroy();
    historyChart = new Chart(canvas.getContext("2d"), {
      type: "line",
      data: {
        labels: history.map((entry) => NW.shortDate(entry.ts)),
        datasets: [
          {
            label: "Online",
            data: history.map((entry) => (entry.online ? 1 : 0)),
            borderColor: "#4fa97a",
            backgroundColor: "rgba(79, 169, 122, 0.09)",
            fill: true,
            stepped: true,
            borderWidth: 1.8,
            pointRadius: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        scales: {
          x: { grid: { display: false }, ticks: { maxTicksLimit: 6 } },
          y: {
            min: 0,
            max: 1,
            ticks: { stepSize: 1, callback: (value) => (value ? "Online" : "Offline") },
            grid: { color: "rgba(154, 170, 190, 0.075)" },
          },
        },
        plugins: { legend: { display: false } },
      },
    });
  }

  function bind() {
    document.getElementById("devices-refresh")?.addEventListener("click", () => load(true));
    document.getElementById("device-search")?.addEventListener("input", (event) => {
      filter = event.target.value;
      renderTable();
    });
    const dialog = document.getElementById("device-scan-dialog");
    document.getElementById("open-scan-dialog")?.addEventListener("click", () => dialog?.showModal());
    document.getElementById("scan-cancel")?.addEventListener("click", () => dialog?.close());
    const consent = document.getElementById("scan-consent");
    const start = document.getElementById("scan-start");
    consent?.addEventListener("change", () => {
      if (start) start.disabled = !consent.checked;
    });
    start?.addEventListener("click", startScan);
    document.getElementById("history-close")?.addEventListener("click", () => {
      document.getElementById("device-history-dialog")?.close();
    });
    document.addEventListener("nw:devices", () => load());
    document.addEventListener("nw:summary", (event) => {
      const iface = event.detail.monitor?.interface;
      if (iface && !devices.length) setText("devices-interface", iface);
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    bind();
    load();
    NW.loadSummary().catch(() => {});
  });
})();
