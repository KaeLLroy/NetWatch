/* NetWatch shared frontend runtime. */
(function () {
  "use strict";

  const NW = (window.NW = {});
  const state = (NW.state = {
    page: document.documentElement.dataset.page || "",
    settings: {
      refresh_interval: 2,
      chart_points: 300,
      notifications_enabled: true,
      compact_mode: false,
      public_ip_enabled: true,
    },
    unread: 0,
    summary: null,
    socket: null,
    internet: null,
  });

  NW.$ = (selector, root = document) => root.querySelector(selector);
  NW.$$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));
  NW.escape = function (value) {
    return String(value ?? "").replace(/[&<>"']/g, (character) => ({
      "&": "&amp;",
      "<": "&lt;",
      ">": "&gt;",
      '"': "&quot;",
      "'": "&#39;",
    })[character]);
  };
  NW.icon = (name, className = "icon") =>
    `<svg class="${className}" aria-hidden="true"><use href="#i-${name}"></use></svg>`;

  /* ------------------------------------------------------------------ API */
  NW.api = async function (path, options = {}) {
    const init = { headers: { Accept: "application/json" }, ...options };
    if (options.body !== undefined && typeof options.body !== "string") {
      init.headers = { ...init.headers, "Content-Type": "application/json" };
      init.body = JSON.stringify(options.body);
    }
    const response = await fetch(path, init);
    let payload = null;
    const contentType = response.headers.get("content-type") || "";
    if (contentType.includes("application/json")) {
      payload = await response.json();
    }
    if (!response.ok || (payload && payload.ok === false)) {
      const message = (payload && payload.error) || `Request failed (${response.status})`;
      const error = new Error(message);
      error.status = response.status;
      throw error;
    }
    return payload ? payload.data : null;
  };

  /* -------------------------------------------------------------- formatters */
  NW.mbps = (bps) => (Number(bps || 0) / 1_000_000).toFixed(2);
  NW.bytes = function (value, precision) {
    const bytes = Math.max(0, Number(value || 0));
    if (bytes < 1024) return { value: String(Math.round(bytes)), unit: "B" };
    const units = ["KB", "MB", "GB", "TB", "PB"];
    let size = bytes / 1024;
    let index = 0;
    while (size >= 1024 && index < units.length - 1) {
      size /= 1024;
      index += 1;
    }
    const digits = precision === undefined ? (size >= 100 ? 1 : 2) : precision;
    return { value: size.toFixed(digits), unit: units[index] };
  };
  NW.byteString = (value, precision) => {
    const parts = NW.bytes(value, precision);
    return `${parts.value} ${parts.unit}`;
  };
  NW.rateParts = (bps) => {
    const value = Number(bps || 0);
    if (value >= 1_000_000_000) return { value: (value / 1_000_000_000).toFixed(2), unit: "Gbps" };
    if (value >= 1_000_000) return { value: (value / 1_000_000).toFixed(2), unit: "Mbps" };
    if (value >= 1_000) return { value: (value / 1_000).toFixed(1), unit: "Kbps" };
    return { value: String(Math.round(value)), unit: "bps" };
  };
  NW.rateString = (bps) => {
    const parts = NW.rateParts(bps);
    return `${parts.value} ${parts.unit}`;
  };
  NW.number = (value) => Number(value || 0).toLocaleString();
  NW.duration = function (seconds) {
    let remaining = Math.max(0, Math.floor(Number(seconds || 0)));
    const days = Math.floor(remaining / 86400);
    remaining %= 86400;
    const hours = Math.floor(remaining / 3600);
    remaining %= 3600;
    const minutes = Math.floor(remaining / 60);
    const secs = remaining % 60;
    if (days) return `${days}d ${String(hours).padStart(2, "0")}h ${String(minutes).padStart(2, "0")}m`;
    if (hours) return `${hours}h ${String(minutes).padStart(2, "0")}m ${String(secs).padStart(2, "0")}s`;
    if (minutes) return `${minutes}m ${String(secs).padStart(2, "0")}s`;
    return `${secs}s`;
  };
  NW.dateTime = (epoch) =>
    epoch
      ? new Date(epoch * 1000).toLocaleString(undefined, {
          year: "numeric",
          month: "short",
          day: "2-digit",
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : "—";
  NW.time = (epoch) =>
    epoch
      ? new Date(epoch * 1000).toLocaleTimeString(undefined, {
          hour: "2-digit",
          minute: "2-digit",
          second: "2-digit",
        })
      : "—";
  NW.shortTime = (epoch) =>
    epoch
      ? new Date(epoch * 1000).toLocaleTimeString(undefined, {
          hour: "2-digit",
          minute: "2-digit",
        })
      : "—";
  NW.shortDate = (epoch) =>
    epoch
      ? new Date(epoch * 1000).toLocaleDateString(undefined, { month: "short", day: "2-digit" })
      : "—";
  NW.relative = function (epoch) {
    if (!epoch) return "never";
    const delta = Math.max(0, Math.floor(Date.now() / 1000 - Number(epoch)));
    if (delta < 10) return "just now";
    if (delta < 60) return `${delta}s ago`;
    if (delta < 3600) return `${Math.floor(delta / 60)}m ago`;
    if (delta < 86400) return `${Math.floor(delta / 3600)}h ago`;
    if (delta < 604800) return `${Math.floor(delta / 86400)}d ago`;
    return NW.shortDate(epoch);
  };

  /* ---------------------------------------------------------------- toasts */
  const toastIcons = { success: "check", error: "warning", warning: "warning", info: "info" };
  const toastTitles = { success: "Success", error: "Error", warning: "Warning", info: "Notice" };
  NW.toast = function (message, type = "info", title) {
    const stack = document.getElementById("toast-stack");
    if (!stack) return;
    const toast = document.createElement("div");
    toast.className = `toast ${type}`;
    toast.innerHTML = `
      <span class="toast-icon">${NW.icon(toastIcons[type] || "info")}</span>
      <div class="toast-body">
        <strong class="toast-title">${NW.escape(title || toastTitles[type] || "Notice")}</strong>
        <p class="toast-message">${NW.escape(message)}</p>
      </div>
      <button class="toast-close" type="button" aria-label="Dismiss notification">${NW.icon("x")}</button>`;
    const dismiss = () => {
      if (toast.classList.contains("is-leaving")) return;
      toast.classList.add("is-leaving");
      setTimeout(() => toast.remove(), 190);
    };
    toast.querySelector(".toast-close").addEventListener("click", dismiss);
    stack.appendChild(toast);
    setTimeout(dismiss, type === "error" ? 7000 : 4800);
  };

  /* --------------------------------------------------------------- dialogs */
  let confirmResolver = null;
  const confirmDialog = document.getElementById("confirm-dialog");
  const confirmTitle = document.getElementById("confirm-title");
  const confirmMessage = document.getElementById("confirm-message");
  const confirmAccept = document.getElementById("confirm-accept");
  const confirmCancel = document.getElementById("confirm-cancel");

  function settleConfirm(value) {
    if (confirmDialog && confirmDialog.open) confirmDialog.close();
    if (confirmResolver) {
      const resolve = confirmResolver;
      confirmResolver = null;
      resolve(value);
    }
  }
  if (confirmDialog) {
    confirmCancel.addEventListener("click", () => settleConfirm(false));
    confirmAccept.addEventListener("click", () => settleConfirm(true));
    confirmDialog.addEventListener("cancel", (event) => {
      event.preventDefault();
      settleConfirm(false);
    });
    confirmDialog.addEventListener("close", () => {
      if (confirmResolver) {
        const resolve = confirmResolver;
        confirmResolver = null;
        resolve(false);
      }
    });
  }
  NW.confirm = function ({
    title = "Confirm action",
    message = "Are you sure you want to continue?",
    confirmLabel = "Confirm",
    danger = false,
  } = {}) {
    if (!confirmDialog) return Promise.resolve(window.confirm(message));
    if (confirmDialog.open) settleConfirm(false);
    confirmTitle.textContent = title;
    confirmMessage.textContent = message;
    confirmAccept.textContent = confirmLabel;
    confirmAccept.className = `btn ${danger ? "btn-danger" : "btn-primary"}`;
    confirmDialog.showModal();
    return new Promise((resolve) => {
      confirmResolver = resolve;
    });
  };

  /* ------------------------------------------------------------- bootstrap */
  let summaryPromise = null;
  let settingsPromise = null;

  function applySummary(summary) {
    state.summary = summary;
    if (summary.settings) Object.assign(state.settings, summary.settings);
    state.unread = Number(summary.unread_alerts || 0);
    updateBadge(state.unread);
    if (summary.monitor) {
      setMonitorState(Boolean(summary.monitor.monitor_running), summary.monitor.last_error);
      updateLink(summary.monitor.internet_online, summary.monitor.internet_latency_ms);
    }
    const hostLabel = document.getElementById("host-chip-label");
    if (hostLabel && summary.system && summary.system.hostname) hostLabel.textContent = summary.system.hostname;
    applyPreferences();
    document.dispatchEvent(new CustomEvent("nw:summary", { detail: summary }));
    return summary;
  }

  NW.loadSummary = function (force = false) {
    if (!summaryPromise || force) {
      summaryPromise = NW.api("/api/dashboard/summary")
        .then(applySummary)
        .catch((error) => {
          summaryPromise = null;
          throw error;
        });
    }
    return summaryPromise;
  };

  NW.loadSettings = function (force = false) {
    if (!settingsPromise || force) {
      settingsPromise = NW.api("/api/settings")
        .then((settings) => {
          state.settings = settings;
          applyPreferences();
          return settings;
        })
        .catch((error) => {
          settingsPromise = null;
          throw error;
        });
    }
    return settingsPromise;
  };

  function applyPreferences() {
    document.body.classList.toggle("compact", Boolean(state.settings.compact_mode));
  }

  function updateBadge(count) {
    state.unread = Number(count || 0);
    const text = state.unread > 99 ? "99+" : String(state.unread);
    ["alert-badge", "nav-alert-count"].forEach((id) => {
      const badge = document.getElementById(id);
      if (!badge) return;
      badge.hidden = state.unread <= 0;
      badge.textContent = text;
    });
  }
  NW.updateBadge = updateBadge;

  function updateLink(online, latency) {
    state.internet = online;
    const container = document.getElementById("link-state");
    const label = document.getElementById("link-state-text");
    if (!container || !label) return;
    const value = online === true ? "online" : online === false ? "offline" : "checking";
    container.dataset.state = value;
    label.textContent = online === true ? "Online" : online === false ? "Offline" : "Checking";
    container.title =
      online === true
        ? `Internet reachable${latency ? ` · ${latency} ms` : ""}`
        : online === false
          ? "Internet unreachable"
          : "Checking internet connectivity";
  }
  NW.updateLink = updateLink;

  function setMonitorState(running, error) {
    const dot = document.getElementById("sidebar-status-dot");
    const text = document.getElementById("sidebar-status-text");
    if (!dot || !text) return;
    dot.dataset.state = running ? "online" : "offline";
    text.textContent = running ? "Sampling live counters" : error ? "Stopped with errors" : "Not running";
  }
  NW.setMonitorState = setMonitorState;

  /* --------------------------------------------------------------- sockets */
  function initSocket() {
    if (typeof window.io !== "function") {
      console.warn("Socket.IO client unavailable; falling back to polling.");
      return;
    }
    const socket = window.io({ transports: ["websocket", "polling"] });
    state.socket = socket;

    socket.on("connect", () => {
      setMonitorState(true);
      socket.emit("client_ready", { page: state.page });
    });
    socket.on("disconnect", () => {
      const dot = document.getElementById("sidebar-status-dot");
      const text = document.getElementById("sidebar-status-text");
      if (dot) dot.dataset.state = "unknown";
      if (text) text.textContent = "Reconnecting…";
    });
    socket.on("telemetry", (payload) => {
      updateLink(payload.internet_online, payload.internet_latency_ms);
      document.dispatchEvent(new CustomEvent("nw:telemetry", { detail: payload }));
    });
    socket.on("connectivity", (payload) => {
      updateLink(payload.online, payload.latency_ms);
      document.dispatchEvent(new CustomEvent("nw:connectivity", { detail: payload }));
    });
    socket.on("alert", (alert) => {
      updateBadge(state.unread + 1);
      if (state.settings.notifications_enabled !== false) {
        const type = alert.severity === "critical" ? "error" : alert.severity === "warning" ? "warning" : "info";
        NW.toast(alert.message, type, alert.severity === "critical" ? "Critical network alert" : "Network alert");
      }
      document.dispatchEvent(new CustomEvent("nw:alert", { detail: alert }));
    });
    socket.on("alerts_updated", (payload) => {
      updateBadge(payload.unread);
      document.dispatchEvent(new CustomEvent("nw:alerts-updated", { detail: payload }));
    });
    socket.on("settings_updated", (settings) => {
      state.settings = settings;
      applyPreferences();
      document.dispatchEvent(new CustomEvent("nw:settings", { detail: settings }));
    });
    socket.on("devices_updated", (payload) => {
      document.dispatchEvent(new CustomEvent("nw:devices", { detail: payload }));
    });
    socket.on("monitor_status", (payload) => {
      setMonitorState(Boolean(payload.running));
    });
  }

  /* ---------------------------------------------------------------- charts */
  NW.chartDefaults = function () {
    if (typeof window.Chart !== "function") return;
    const Chart = window.Chart;
    Chart.defaults.color = "#8a97a8";
    Chart.defaults.borderColor = "rgba(154, 170, 190, 0.09)";
    Chart.defaults.font.family = getComputedStyle(document.body).fontFamily;
    Chart.defaults.font.size = 9.5;
    Chart.defaults.animation.duration = 260;
    Chart.defaults.plugins.legend.display = false;
    Chart.defaults.plugins.tooltip.backgroundColor = "rgba(15, 20, 25, 0.97)";
    Chart.defaults.plugins.tooltip.borderColor = "#2c3641";
    Chart.defaults.plugins.tooltip.borderWidth = 1;
    Chart.defaults.plugins.tooltip.titleColor = "#d9e1eb";
    Chart.defaults.plugins.tooltip.bodyColor = "#a9b6c5";
    Chart.defaults.plugins.tooltip.padding = 9;
    Chart.defaults.plugins.tooltip.cornerRadius = 3;
    Chart.defaults.plugins.tooltip.displayColors = true;
    Chart.defaults.plugins.tooltip.boxPadding = 4;
    Chart.defaults.plugins.tooltip.usePointStyle = true;
  };

  NW.gradient = function (context, color) {
    const gradient = context.createLinearGradient(0, 0, 0, context.canvas.clientHeight || 260);
    gradient.addColorStop(0, color.replace("ALPHA", "0.12"));
    gradient.addColorStop(1, color.replace("ALPHA", "0"));
    return gradient;
  };

  NW.axisRate = function (value) {
    const number = Number(value || 0);
    if (number >= 1_000_000) return `${(number / 1_000_000).toFixed(1)}M`;
    if (number >= 1_000) return `${(number / 1_000).toFixed(0)}K`;
    return `${Math.round(number)}`;
  };

  NW.baseScales = function (yTitle = "bps") {
    return {
      x: {
        grid: { display: false },
        border: { display: false },
        ticks: { maxRotation: 0, autoSkip: true, maxTicksLimit: 8, color: "#6b7889" },
      },
      y: {
        beginAtZero: true,
        border: { display: false },
        grid: { color: "rgba(154, 170, 190, 0.075)", drawTicks: false },
        ticks: {
          color: "#6b7889",
          padding: 8,
          callback: (value) => NW.axisRate(value),
        },
        title: { display: false, text: yTitle },
      },
    };
  };

  /* ------------------------------------------------------------------ shell */
  function initShell() {
    const clock = document.getElementById("topbar-clock");
    const tick = () => {
      if (!clock) return;
      clock.textContent = new Date().toLocaleTimeString(undefined, {
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    };
    tick();
    setInterval(tick, 1000);

    const sidebar = document.getElementById("sidebar");
    const scrim = document.getElementById("sidebar-scrim");
    const menu = document.getElementById("menu-button");
    const setOpen = (open) => {
      if (!sidebar || !scrim || !menu) return;
      sidebar.classList.toggle("is-open", open);
      scrim.hidden = !open;
      menu.setAttribute("aria-expanded", String(open));
      document.body.classList.toggle("nav-open", open);
    };
    if (menu) menu.addEventListener("click", () => setOpen(!sidebar.classList.contains("is-open")));
    if (scrim) scrim.addEventListener("click", () => setOpen(false));
    document.addEventListener("keydown", (event) => {
      if (event.key === "Escape") setOpen(false);
    });

    NW.chartDefaults();
    initSocket();

    NW.loadSummary().catch((error) => {
      console.error("Initial summary failed", error);
      NW.toast(error.message, "error", "Unable to load dashboard");
    });
    NW.loadSettings().catch(() => {});
    setInterval(() => {
      if (state.socket && state.socket.connected) return;
      NW.loadSummary(true).catch(() => {});
    }, 15000);
    setInterval(() => {
      NW.loadSummary(true).catch(() => {});
    }, 45000);
  }

  NW.debounce = function (fn, delay = 200) {
    let timer = null;
    return function (...args) {
      clearTimeout(timer);
      timer = setTimeout(() => fn.apply(this, args), delay);
    };
  };

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initShell);
  } else {
    initShell();
  }
})();
