/* Traffic — historical bandwidth, daily aggregates, and totals. */
(function () {
  "use strict";
  const NW = window.NW;

  const RANGE_LABELS = {
    "1h": "Last hour",
    "6h": "Last 6 hours",
    "24h": "Last 24 hours",
    "7d": "Last 7 days",
    "30d": "Last 30 days",
  };
  let range = "24h";
  let chart = null;
  let dailyChart = null;
  let selectedInterface = "";
  let initialized = false;

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  function createLineChart() {
    const canvas = document.getElementById("traffic-chart");
    if (!canvas || typeof Chart !== "function") return;
    const context = canvas.getContext("2d");
    chart = new Chart(context, {
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
            borderWidth: 1.7,
            pointRadius: 0,
            pointHitRadius: 8,
            tension: 0.28,
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
            tension: 0.28,
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
    const canvas = document.getElementById("daily-chart");
    if (!canvas || typeof Chart !== "function") return;
    dailyChart = new Chart(canvas.getContext("2d"), {
      type: "bar",
      data: {
        labels: [],
        datasets: [
          { label: "Downloaded", data: [], backgroundColor: "rgba(82, 184, 208, 0.6)", borderRadius: 2, maxBarThickness: 16 },
          { label: "Uploaded", data: [], backgroundColor: "rgba(130, 145, 196, 0.6)", borderRadius: 2, maxBarThickness: 16 },
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

  function updateHistory(data) {
    if (!chart) return;
    const points = data.points || [];
    chart.data.labels = points.map((point) => {
      const date = new Date(point.bucket_ts * 1000);
      if (range === "7d" || range === "30d") {
        return date.toLocaleDateString(undefined, { month: "short", day: "2-digit" });
      }
      return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit" });
    });
    chart.data.datasets[0].data = points.map((point) => Number(point.download_bps || 0));
    chart.data.datasets[1].data = points.map((point) => Number(point.upload_bps || 0));
    const pointRadius = points.length <= 2 ? 2.5 : 0;
    chart.data.datasets.forEach((dataset) => {
      dataset.pointRadius = pointRadius;
    });
    chart.update();

    const summary = data.summary || {};
    const total = Number(summary.bytes_recv || 0) + Number(summary.bytes_sent || 0);
    const parts = NW.bytes(total);
    setText("traffic-total", parts.value);
    setText("traffic-total-unit", parts.unit);
    setText("traffic-peak", NW.mbps(summary.peak_download_bps));
    setText("traffic-range-label", RANGE_LABELS[range]);
    setText("traffic-sample-chip", `${points.length} buckets`);
    setText("traffic-chart-subtitle", `${RANGE_LABELS[range]} · ${data.interface || "no active interface"}`);
  }

  function updateDaily(rows) {
    if (!dailyChart) return;
    dailyChart.data.labels = rows.map((row) =>
      new Date(`${row.date}T00:00:00`).toLocaleDateString(undefined, { month: "short", day: "2-digit" })
    );
    dailyChart.data.datasets[0].data = rows.map((row) => Number(row.bytes_recv || 0) / 1024 / 1024);
    dailyChart.data.datasets[1].data = rows.map((row) => Number(row.bytes_sent || 0) / 1024 / 1024);
    dailyChart.update();

    const body = document.getElementById("daily-table-body");
    if (!body) return;
    if (!rows.length) {
      body.innerHTML = `<tr><td colspan="6" class="table-empty">No daily statistics have been recorded yet.</td></tr>`;
      return;
    }
    body.innerHTML = rows
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
  }

  function updatePeriods(data) {
    setText("period-today", NW.byteString((data.today?.bytes_recv || 0) + (data.today?.bytes_sent || 0)));
    setText("period-week", NW.byteString((data.week?.bytes_recv || 0) + (data.week?.bytes_sent || 0)));
    setText("period-month", NW.byteString((data.month?.bytes_recv || 0) + (data.month?.bytes_sent || 0)));
    setText("period-lifetime", NW.byteString((data.lifetime?.bytes_recv || 0) + (data.lifetime?.bytes_sent || 0)));
  }

  function updateLive(point) {
    if (!point) {
      setText("traffic-down", "0.00");
      setText("traffic-up", "0.00");
      return;
    }
    setText("traffic-down", NW.mbps(point.download_bps));
    setText("traffic-up", NW.mbps(point.upload_bps));
  }

  async function loadInterfaces() {
    const select = document.getElementById("traffic-interface");
    if (!select) return;
    try {
      const data = await NW.api("/api/interfaces");
      const current = selectedInterface || data.primary || "";
      select.innerHTML = (data.interfaces || [])
        .map(
          (item) =>
            `<option value="${NW.escape(item.name)}"${item.name === current ? " selected" : ""}>${NW.escape(item.name)}${item.is_up ? "" : " (down)"}</option>`
        )
        .join("");
      selectedInterface = select.value || current;
      updateExportLink();
    } catch (error) {
      NW.toast(error.message, "error", "Unable to load interfaces");
    }
  }

  function updateExportLink() {
    const link = document.getElementById("export-traffic");
    if (link) {
      const query = new URLSearchParams({ days: "30" });
      if (selectedInterface) query.set("interface", selectedInterface);
      link.href = `/api/traffic/export.csv?${query.toString()}`;
    }
  }

  async function loadLive() {
    try {
      const query = new URLSearchParams({ points: "1" });
      if (selectedInterface) query.set("interface", selectedInterface);
      const data = await NW.api(`/api/traffic/live?${query.toString()}`);
      updateLive(data.points?.[data.points.length - 1]);
    } catch {
      updateLive(null);
    }
  }

  async function loadAll() {
    const button = document.getElementById("traffic-refresh");
    if (button) button.disabled = true;
    try {
      const ifaceQuery = selectedInterface ? `&interface=${encodeURIComponent(selectedInterface)}` : "";
      const [history, daily, periods] = await Promise.all([
        NW.api(`/api/traffic/history?range=${range}${ifaceQuery}`),
        NW.api(`/api/traffic/daily?days=14${ifaceQuery}`),
        NW.api(`/api/traffic/summary?interface=${encodeURIComponent(selectedInterface)}`),
      ]);
      updateHistory(history);
      updateDaily(daily.daily || []);
      updatePeriods(periods);
      await loadLive();
    } catch (error) {
      NW.toast(error.message, "error", "Traffic data unavailable");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function bind() {
    NW.$$("#traffic-range button").forEach((button) => {
      button.addEventListener("click", () => {
        range = button.dataset.range;
        NW.$$("#traffic-range button").forEach((item) => item.classList.toggle("is-active", item === button));
        loadAll();
      });
    });
    document.getElementById("traffic-interface")?.addEventListener("change", (event) => {
      selectedInterface = event.target.value;
      updateExportLink();
      loadAll();
    });
    document.getElementById("traffic-refresh")?.addEventListener("click", loadAll);
    document.addEventListener("nw:telemetry", (event) => {
      const payload = event.detail;
      if (!selectedInterface || payload.interface === selectedInterface) {
        updateLive({ download_bps: payload.download_bps, upload_bps: payload.upload_bps });
      }
    });
    document.addEventListener("nw:settings", () => loadInterfaces());
  }

  document.addEventListener("DOMContentLoaded", async () => {
    createLineChart();
    createDailyChart();
    bind();
    try {
      const summary = await NW.loadSummary();
      selectedInterface = summary.monitor?.interface || "";
      await loadInterfaces();
    } catch {
      await loadInterfaces();
    }
    await loadAll();
    initialized = true;
    setInterval(() => {
      if (!document.hidden && initialized) loadAll();
    }, 60000);
  });
})();
