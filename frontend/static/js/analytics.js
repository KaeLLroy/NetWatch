/* Analytics — historical trends, connectivity, discovery, and summaries. */
(function () {
  "use strict";
  const NW = window.NW;

  let days = 7;
  let charts = {};
  let loading = false;

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  function rangeLabel() {
    return `Last ${days} days`;
  }

  function createBandwidthChart() {
    const canvas = document.getElementById("analytics-bandwidth-chart");
    if (!canvas || typeof Chart !== "function") return;
    const context = canvas.getContext("2d");
    charts.bandwidth = new Chart(context, {
      type: "line",
      data: {
        labels: [],
        datasets: [
          {
            label: "Download",
            data: [],
            borderColor: "#52b8d0",
            backgroundColor: NW.gradient(context, "rgba(82, 184, 208, ALPHA)"),
            fill: true,
            borderWidth: 1.8,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.3,
          },
          {
            label: "Upload",
            data: [],
            borderColor: "#8291c4",
            backgroundColor: "transparent",
            fill: false,
            borderWidth: 1.5,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.3,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: NW.baseScales("bps"),
        plugins: {
          tooltip: {
            callbacks: {
              label: (context) => `${context.dataset.label}: ${NW.rateString(context.parsed.y)}`,
            },
          },
        },
      },
    });
  }

  function createDailyChart() {
    const canvas = document.getElementById("analytics-daily-chart");
    if (!canvas || typeof Chart !== "function") return;
    charts.daily = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          {
            label: "Downloaded",
            data: [],
            backgroundColor: "rgba(82, 184, 208, 0.6)",
            borderRadius: 2,
            maxBarThickness: 18,
          },
          {
            label: "Uploaded",
            data: [],
            backgroundColor: "rgba(130, 145, 196, 0.6)",
            borderRadius: 2,
            maxBarThickness: 18,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          ...NW.baseScales(),
          y: {
            ...NW.baseScales().y,
            ticks: {
              color: "#6b7889",
              padding: 8,
              callback: (value) => `${value} MB`,
            },
          },
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: (context) => `${context.dataset.label}: ${NW.byteString(context.parsed.y * 1024 * 1024)}`,
            },
          },
        },
      },
    });
  }

  function createDiscoveryChart() {
    const canvas = document.getElementById("discovery-chart");
    if (!canvas || typeof Chart !== "function") return;
    charts.discovery = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          {
            label: "Devices",
            data: [],
            backgroundColor: "rgba(79, 169, 122, 0.62)",
            hoverBackgroundColor: "rgba(79, 169, 122, 0.85)",
            borderRadius: 2,
            maxBarThickness: 18,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        interaction: { mode: "index", intersect: false },
        scales: {
          ...NW.baseScales(),
          y: {
            beginAtZero: true,
            border: { display: false },
            grid: { color: "rgba(154, 170, 190, 0.075)", drawTicks: false },
            ticks: { color: "#5f7187", padding: 8, precision: 0 },
          },
        },
        plugins: {
          tooltip: {
            callbacks: {
              label: (context) => `${context.parsed.y} responsive device(s)`,
            },
          },
        },
      },
    });
  }

  function createUptimeChart() {
    const canvas = document.getElementById("uptime-chart");
    if (!canvas || typeof Chart !== "function") return;
    charts.uptime = new Chart(canvas.getContext("2d"), {
      type: "doughnut",
      data: {
        labels: ["Online", "Offline"],
        datasets: [
          {
            data: [0, 1],
            backgroundColor: ["#4fa97a", "rgba(148, 163, 184, 0.16)"],
            borderWidth: 0,
            hoverOffset: 2,
          },
        ],
      },
      options: {
        responsive: true,
        maintainAspectRatio: false,
        cutout: "74%",
        plugins: {
          tooltip: {
            callbacks: {
              label: (context) => {
                const value = Number(context.parsed || 0);
                return context.label === "Online" ? `${value} online checks` : `${value} failed checks`;
              },
            },
          },
        },
      },
    });
  }

  function updateOverview(data) {
    setText("analytics-range-label", rangeLabel());
    const averageDown = NW.rateParts(data.average_download_bps);
    const averageUp = NW.rateParts(data.average_upload_bps);
    setText("analytics-avg-down", averageDown.value);
    setText("analytics-avg-down-unit", averageDown.unit);
    setText("analytics-avg-up", averageUp.value);
    setText("analytics-avg-up-unit", averageUp.unit);

    const down = NW.bytes(data.totals?.bytes_recv || 0);
    const up = NW.bytes(data.totals?.bytes_sent || 0);
    setText("analytics-total-down", down.value);
    setText("analytics-total-down-unit", down.unit);
    setText("analytics-total-up", up.value);
    setText("analytics-total-up-unit", up.unit);

    const connectivity = data.connectivity || {};
    const uptime = connectivity.uptime_percent;
    setText("analytics-uptime", uptime === null || uptime === undefined ? "—" : uptime.toFixed(1));
    setText(
      "analytics-uptime-samples",
      connectivity.total
        ? `${connectivity.online}/${connectivity.total} checks · ${connectivity.avg_latency_ms ?? "—"} ms avg`
        : "No checks recorded"
    );
    if (charts.uptime) {
      const online = Number(connectivity.online || 0);
      const offline = Math.max(0, Number(connectivity.total || 0) - online);
      charts.uptime.data.datasets[0].data = connectivity.total ? [online, offline] : [0, 1];
      charts.uptime.data.datasets[0].backgroundColor = connectivity.total
        ? ["#4fa97a", "rgba(221, 107, 107, 0.55)"]
        : ["rgba(148, 163, 184, 0.16)", "rgba(148, 163, 184, 0.16)"];
      charts.uptime.update();
    }
    setText("uptime-center", uptime === null || uptime === undefined ? "—" : `${uptime.toFixed(1)}%`);

    renderInterfaceUsage(data.interfaces || []);
    renderAlertBreakdown(data.alerts || {});
    renderWeekly(data.daily || []);
  }

  function renderInterfaceUsage(rows) {
    const body = document.getElementById("interface-usage-body");
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="4" class="table-empty">No interface data recorded in this period.</td></tr>`;
      return;
    }
    body.innerHTML = rows
      .map(
        (row) => `<tr>
          <td>${NW.escape(row.interface || "Unknown")}</td>
          <td class="num">${NW.byteString(row.bytes_recv)}</td>
          <td class="num">${NW.byteString(row.bytes_sent)}</td>
          <td class="num">${NW.rateString(row.download_peak_bps)}</td>
        </tr>`
      )
      .join("");
  }

  function renderAlertBreakdown(alerts) {
    const container = document.getElementById("alert-breakdown");
    if (!container) return;
    const rows = alerts.by_type || [];
    if (!rows.length) {
      container.innerHTML = `<div class="empty-state compact-empty">${NW.icon("shield")}<p>No alerts recorded in this period.</p></div>`;
      return;
    }
    const maximum = Math.max(1, ...rows.map((row) => Number(row.count || 0)));
    container.innerHTML = rows
      .map((row) => {
        const count = Number(row.count || 0);
        const label = String(row.type || "event").replaceAll("_", " ");
        return `<div class="breakdown-row">
          <span class="breakdown-name">${NW.escape(label)}</span>
          <span class="breakdown-count">${NW.number(count)}</span>
          <span class="breakdown-bar"><span style="width:${Math.round((count / maximum) * 100)}%"></span></span>
        </div>`;
      })
      .join("");
  }

  function renderWeekly(rows) {
    const body = document.getElementById("weekly-body");
    if (!body) return;
    const recent = rows.slice(-7);
    if (!recent.length) {
      body.innerHTML = `<tr><td colspan="6" class="table-empty">No daily aggregates recorded.</td></tr>`;
      setText("weekly-total-chip", "No data");
      return;
    }
    body.innerHTML = recent
      .slice()
      .reverse()
      .map(
        (row) => `<tr>
          <td>${NW.escape(row.date)}</td>
          <td class="num">${NW.byteString(row.bytes_recv)}</td>
          <td class="num">${NW.byteString(row.bytes_sent)}</td>
          <td class="num">${NW.rateString(row.download_peak_bps)}</td>
          <td class="num">${NW.rateString(row.upload_peak_bps)}</td>
          <td class="num">${NW.number(row.samples)}</td>
        </tr>`
      )
      .join("");
    const total = recent.reduce(
      (sum, row) => sum + Number(row.bytes_recv || 0) + Number(row.bytes_sent || 0),
      0
    );
    setText("weekly-total-chip", `${NW.byteString(total)} across ${recent.length} day(s)`);
  }

  function updateDailyChart(rows) {
    if (!charts.daily) return;
    charts.daily.data.labels = rows.map((row) =>
      new Date(`${row.date}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "2-digit" })
    );
    charts.daily.data.datasets[0].data = rows.map((row) => Number(row.bytes_recv || 0) / 1024 / 1024);
    charts.daily.data.datasets[1].data = rows.map((row) => Number(row.bytes_sent || 0) / 1024 / 1024);
    charts.daily.update();
  }

  function updateBandwidthChart(data) {
    if (!charts.bandwidth) return;
    const rows = data.hourly || [];
    charts.bandwidth.data.labels = rows.map((row) => {
      const date = new Date(row.bucket_ts * 1000);
      return days <= 2
        ? date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" })
        : date.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
    });
    charts.bandwidth.data.datasets[0].data = rows.map((row) => Number(row.download_bps || 0));
    charts.bandwidth.data.datasets[1].data = rows.map((row) => Number(row.upload_bps || 0));
    const pointRadius = rows.length <= 2 ? 2.5 : 0;
    charts.bandwidth.data.datasets.forEach((dataset) => {
      dataset.pointRadius = pointRadius;
    });
    charts.bandwidth.update();
    setText("analytics-interface-chip", data.interface || "No active interface");
    updateDailyChart(data.daily || []);
  }

  function updateDiscoveryChart(data) {
    if (!charts.discovery) return;
    const rows = data.timeline || [];
    charts.discovery.data.labels = rows.map((row) =>
      new Date(row.day_ts * 1000).toLocaleDateString(undefined, { month: "short", day: "2-digit" })
    );
    charts.discovery.data.datasets[0].data = rows.map((row) => Number(row.devices || 0));
    charts.discovery.update();
  }

  async function load(showToast = false) {
    if (loading) return;
    loading = true;
    const button = document.getElementById("analytics-refresh");
    if (button) button.disabled = true;
    try {
      const [overview, bandwidth, discovery] = await Promise.all([
        NW.api(`/api/analytics/overview?days=${days}`),
        NW.api(`/api/analytics/bandwidth?days=${days}`),
        NW.api(`/api/analytics/devices?days=${days}`),
      ]);
      updateOverview(overview);
      updateBandwidthChart(bandwidth);
      updateDiscoveryChart(discovery);
      const link = document.getElementById("analytics-export");
      if (link) link.href = `/api/traffic/export.csv?days=${days}`;
      if (showToast) NW.toast("Historical analytics refreshed.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Analytics unavailable");
    } finally {
      loading = false;
      if (button) button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    createBandwidthChart();
    createDailyChart();
    createDiscoveryChart();
    createUptimeChart();

    NW.$$("#analytics-range button").forEach((button) => {
      button.addEventListener("click", () => {
        days = Number(button.dataset.days) || 7;
        NW.$$("#analytics-range button").forEach((item) =>
          item.classList.toggle("is-active", item === button)
        );
        load();
      });
    });
    document.getElementById("analytics-refresh")?.addEventListener("click", () => load(true));
    document.addEventListener("nw:settings", () => load());
    load();
    setInterval(() => {
      if (!document.hidden) load();
    }, 120000);
  });
})();
