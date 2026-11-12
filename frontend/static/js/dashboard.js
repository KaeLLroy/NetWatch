/* Dashboard — live telemetry and operational snapshot. */
(function () {
  "use strict";
  const NW = window.NW;

  let chart = null;
  let chartPoints = 300;
  let labels = [];
  let downloadSeries = [];
  let uploadSeries = [];
  let todayReceived = 0;
  let todaySent = 0;
  let lastInterface = null;

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  function initChart() {
    if (typeof Chart !== "function") return;
    const canvas = document.getElementById("live-chart");
    if (!canvas) return;
    const context = canvas.getContext("2d");
    chart = new Chart(context, {
      type: "line",
      data: {
        labels,
        datasets: [
          {
            label: "Download",
            data: downloadSeries,
            borderColor: "#52b8d0",
            backgroundColor: NW.gradient(context, "rgba(82, 184, 208, ALPHA)"),
            fill: true,
            borderWidth: 1.8,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.32,
          },
          {
            label: "Upload",
            data: uploadSeries,
            borderColor: "#8291c4",
            backgroundColor: "transparent",
            fill: false,
            borderWidth: 1.6,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.32,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: NW.baseScales("bps"),
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              title: (items) => items[0]?.label || "",
              label: (context) => `${context.dataset.label}: ${NW.rateString(context.parsed.y)}`,
            },
          },
        },
      },
    });
  }

  function replaceSeries(points) {
    labels = points.map((point) => NW.time(point.ts));
    downloadSeries = points.map((point) => Number(point.download_bps || 0));
    uploadSeries = points.map((point) => Number(point.upload_bps || 0));
    if (!chart) return;
    const pointRadius = points.length <= 2 ? 2.5 : 0;
    chart.data.datasets.forEach((dataset) => {
      dataset.pointRadius = pointRadius;
    });
    chart.data.labels = labels;
    chart.data.datasets[0].data = downloadSeries;
    chart.data.datasets[1].data = uploadSeries;
    chart.update();
  }

  async function loadChart() {
    try {
      const data = await NW.api(`/api/traffic/live?points=${chartPoints}`);
      replaceSeries(data.points || []);
      const chartInterface = document.getElementById("chart-interface");
      if (chartInterface) chartInterface.textContent = data.interface || "No active interface";
    } catch (error) {
      NW.toast(error.message, "error", "Live chart unavailable");
    }
  }

  function appendTelemetry(payload) {
    if (!chart) return;
    if (payload.interface && lastInterface && payload.interface !== lastInterface) {
      loadChart();
      lastInterface = payload.interface;
      return;
    }
    lastInterface = payload.interface || lastInterface;
    labels.push(NW.time(payload.timestamp));
    downloadSeries.push(Number(payload.download_bps || 0));
    uploadSeries.push(Number(payload.upload_bps || 0));
    while (labels.length > chartPoints) {
      labels.shift();
      downloadSeries.shift();
      uploadSeries.shift();
    }
    chart.data.datasets.forEach((dataset) => {
      dataset.pointRadius = labels.length <= 2 ? 2.5 : 0;
    });
    chart.update("none");
  }

  function renderSummary(summary) {
    const monitor = summary.monitor || {};
    const settings = summary.settings || {};
    chartPoints = [30, 90, 300].includes(Number(settings.chart_points)) ? Number(settings.chart_points) : 300;
    setText("chart-interval", settings.refresh_interval || 2);
    setText("last-sample", NW.time(monitor.timestamp));
    setText("metric-download", NW.mbps(monitor.download_bps));
    setText("metric-upload", NW.mbps(monitor.upload_bps));

    if (summary.today) {
      todayReceived = Number(summary.today.bytes_recv || 0);
      todaySent = Number(summary.today.bytes_sent || 0);
      renderTotals();
    }
    const totalLabel = monitor.interface ? `Today on ${monitor.interface}` : "Current interface";
    setText("downloaded-context", totalLabel);
    setText("uploaded-context", totalLabel);

    setText("detail-interface", monitor.interface || "No active adapter");
    setText("detail-local-ip", monitor.local_ip || "Unavailable");
    setText("detail-public-ip", monitor.public_ip || "Unavailable");
    setText("detail-link-speed", monitor.link_speed_mbps ? `${monitor.link_speed_mbps} Mbps` : "Unknown");
    setText("detail-latency", monitor.internet_latency_ms ? `${monitor.internet_latency_ms} ms` : "—");
    setText("detail-uptime", NW.duration(monitor.system_uptime_seconds));
    setText("detail-hostname", summary.system?.hostname || "—");

    const internet = document.getElementById("detail-internet");
    if (internet) {
      const online = monitor.internet_online;
      internet.dataset.state = online === true ? "online" : online === false ? "offline" : "checking";
      internet.innerHTML = `<span class="status-dot"></span>${online === true ? "Reachable" : online === false ? "Unreachable" : "Checking"}`;
    }
    const chip = document.getElementById("connection-chip");
    if (chip) {
      chip.innerHTML = `<span class="status-dot" data-state="${monitor.interface_status === "up" ? "online" : "offline"}"></span>${
        monitor.interface_status === "up" ? "Link up" : "Link down"
      }`;
    }
    setText("chart-interface", monitor.interface || "No active interface");
    setText("chart-interval", settings.refresh_interval || 2);
    renderInterfaces(summary.interface);
    loadAlerts();
  }

  function renderTotals() {
    const received = NW.bytes(todayReceived);
    const sent = NW.bytes(todaySent);
    setText("metric-downloaded", received.value);
    setText("unit-downloaded", received.unit);
    setText("metric-uploaded", sent.value);
    setText("unit-uploaded", sent.unit);
  }

  function interfaceIcon(type) {
    return { wifi: "wifi", virtual: "server", vpn: "shield", loopback: "refresh" }[type] || "interfaces";
  }

  function renderInterfaces(data) {
    const container = document.getElementById("dashboard-interfaces");
    if (!container) return;
    const interfaces = (data?.interfaces || []).slice().sort((a, b) => {
      if (a.is_primary !== b.is_primary) return a.is_primary ? -1 : 1;
      if (a.is_up !== b.is_up) return a.is_up ? -1 : 1;
      return b.bytes_recv + b.bytes_sent - (a.bytes_recv + a.bytes_sent);
    });
    if (!interfaces.length) {
      container.innerHTML = `<div class="empty-state compact-empty"><p>No network adapters detected.</p></div>`;
      return;
    }
    const maximum = Math.max(1, ...interfaces.map((item) => item.bytes_recv + item.bytes_sent));
    container.innerHTML = interfaces
      .slice(0, 5)
      .map((item) => {
        const total = item.bytes_recv + item.bytes_sent;
        const percent = Math.min(100, (total / maximum) * 100);
        return `<div class="adapter-row">
          <span class="adapter-icon ${item.is_up ? "is-up" : ""}">${NW.icon(interfaceIcon(item.type))}</span>
          <div class="adapter-main">
            <div class="adapter-name">${NW.escape(item.name)} ${item.is_primary ? '<span class="chip">Primary</span>' : ""}</div>
            <div class="adapter-sub"><span>${NW.escape(item.ipv4 || "No IPv4")}</span><span>${item.is_up ? "Operational" : "Down"}</span><span>${NW.escape(item.mac || "No MAC")}</span></div>
          </div>
          <div class="adapter-bar" title="Total bytes since adapter start">
            <div class="adapter-bar-track"><span class="adapter-bar-fill" style="width:${percent}%"></span></div>
          </div>
          <div class="adapter-total">${NW.byteString(total)}</div>
        </div>`;
      })
      .join("");
  }

  async function loadAlerts() {
    const container = document.getElementById("dashboard-alerts");
    if (!container) return;
    try {
      const data = await NW.api("/api/alerts?limit=4");
      const alerts = data.alerts || [];
      if (!alerts.length) {
        container.innerHTML = `<div class="empty-state compact-empty">${NW.icon("shield")}<p>No alerts recorded. The network is operating without reported events.</p></div>`;
        return;
      }
      container.innerHTML = alerts
        .map((alert) => {
          const icon = alert.severity === "critical" ? "warning" : alert.severity === "warning" ? "activity" : "info";
          return `<div class="alert-mini severity-${NW.escape(alert.severity)}">
            <span class="alert-mini-icon">${NW.icon(icon)}</span>
            <div class="alert-mini-body"><p>${NW.escape(alert.message)}</p><span>${NW.escape(alert.type.replaceAll("_", " "))} · ${NW.relative(alert.ts)}</span></div>
          </div>`;
        })
        .join("");
    } catch {
      container.innerHTML = `<div class="empty-state compact-empty"><p>Unable to load alerts.</p></div>`;
    }
  }

  async function refresh(showToast = false) {
    try {
      const summary = await NW.loadSummary(true);
      renderSummary(summary);
      await loadChart();
      if (showToast) NW.toast("Dashboard refreshed.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Refresh failed");
    }
  }

  function bind() {
    const buttons = NW.$$("#live-range button");
    buttons.forEach((button) => {
      if (Number(button.dataset.points) === chartPoints) button.classList.add("is-active");
      else button.classList.remove("is-active");
      button.addEventListener("click", () => {
        chartPoints = Number(button.dataset.points);
        buttons.forEach((item) => item.classList.toggle("is-active", item === button));
        loadChart();
      });
    });
    document.getElementById("dashboard-refresh")?.addEventListener("click", () => refresh(true));
    document.addEventListener("nw:summary", (event) => renderSummary(event.detail));
    document.addEventListener("nw:telemetry", (event) => {
      const payload = event.detail;
      setText("metric-download", NW.mbps(payload.download_bps));
      setText("metric-upload", NW.mbps(payload.upload_bps));
      setText("last-sample", NW.time(payload.timestamp));
      setText("detail-uptime", NW.duration(payload.system_uptime_seconds));
      todayReceived += Number(payload.bytes_recv_delta || 0);
      todaySent += Number(payload.bytes_sent_delta || 0);
      renderTotals();
      appendTelemetry(payload);
    });
    document.addEventListener("nw:connectivity", (event) => {
      const payload = event.detail;
      setText("detail-public-ip", payload.public_ip || "Unavailable");
      setText("detail-latency", payload.latency_ms ? `${payload.latency_ms} ms` : "—");
      const internet = document.getElementById("detail-internet");
      if (internet) {
        internet.dataset.state = payload.online ? "online" : "offline";
        internet.innerHTML = `<span class="status-dot"></span>${payload.online ? "Reachable" : "Unreachable"}`;
      }
    });
    document.addEventListener("nw:alert", () => loadAlerts());
    document.addEventListener("nw:alerts-updated", () => loadAlerts());
  }

  document.addEventListener("DOMContentLoaded", async () => {
    initChart();
    bind();
    try {
      const summary = await NW.loadSummary();
      renderSummary(summary);
      lastInterface = summary.monitor?.interface || null;
      const points = [30, 90, 300].includes(Number(summary.settings?.chart_points))
        ? Number(summary.settings.chart_points)
        : 300;
      chartPoints = points;
      NW.$$("#live-range button").forEach((button) =>
        button.classList.toggle("is-active", Number(button.dataset.points) === chartPoints)
      );
      await loadChart();
    } catch (error) {
      NW.toast(error.message, "error", "Unable to load dashboard");
    }
  });
})();
