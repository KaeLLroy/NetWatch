/* Settings — persisted monitoring, alerting, retention, and system information. */
(function () {
  "use strict";
  const NW = window.NW;

  let interfaces = [];

  const byId = (id) => document.getElementById(id);
  const setText = (id, value) => {
    const element = byId(id);
    if (element) element.textContent = value;
  };

  function ensureOption(select, value, label) {
    if (!select) return;
    const text = String(value);
    if (Array.from(select.options).some((option) => option.value === text)) return;
    const option = document.createElement("option");
    option.value = text;
    option.textContent = label || text;
    select.appendChild(option);
  }

  function populateInterfaces(selected) {
    const select = byId("setting-interface");
    if (!select) return;
    const current = selected ?? select.value ?? "";
    select.innerHTML = '<option value="">Automatic (Windows default route)</option>';
    interfaces.forEach((item) => {
      const option = document.createElement("option");
      option.value = item.name;
      option.textContent = `${item.name}${item.is_up ? "" : " (down)"}${item.is_primary ? " · primary" : ""}`;
      select.appendChild(option);
    });
    ensureOption(select, current, current || "Automatic (Windows default route)");
    select.value = current;
  }

  function populate(settings) {
    const refresh = byId("setting-refresh");
    if (refresh) {
      ensureOption(refresh, settings.refresh_interval, `${settings.refresh_interval} seconds`);
      refresh.value = String(settings.refresh_interval);
    }
    const chartPoints = byId("setting-chart-points");
    if (chartPoints) {
      ensureOption(chartPoints, settings.chart_points, `${settings.chart_points} samples`);
      chartPoints.value = String(settings.chart_points);
    }
    const timeout = byId("setting-discovery-timeout");
    if (timeout) {
      ensureOption(timeout, settings.discovery_timeout_ms, `${settings.discovery_timeout_ms} ms`);
      timeout.value = String(settings.discovery_timeout_ms);
    }
    if (byId("setting-down-threshold")) byId("setting-down-threshold").value = settings.download_threshold_mbps;
    if (byId("setting-up-threshold")) byId("setting-up-threshold").value = settings.upload_threshold_mbps;
    if (byId("setting-cooldown")) byId("setting-cooldown").value = settings.alert_cooldown_seconds;
    if (byId("setting-retention")) byId("setting-retention").value = settings.retention_days;
    if (byId("setting-notifications")) byId("setting-notifications").checked = Boolean(settings.notifications_enabled);
    if (byId("setting-public-ip")) byId("setting-public-ip").checked = Boolean(settings.public_ip_enabled);
    if (byId("setting-compact")) byId("setting-compact").checked = Boolean(settings.compact_mode);
    populateInterfaces(settings.interface || "");
  }

  function renderSystem(info) {
    setText("sys-version", `NetWatch ${info.version}`);
    setText("sys-python", info.python || "—");
    setText("sys-hostname", info.hostname || "—");
    setText("sys-platform", info.platform || "—");
    setText(
      "sys-monitor",
      info.monitor_running ? "Running" : info.monitor_error ? "Stopped with errors" : "Stopped"
    );
    setText("sys-interfaces", `${info.interfaces ?? 0} adapters`);
    setText("sys-db-size", NW.byteString(info.database_size || 0));
    setText("sys-data-dir", info.data_dir || "—");
    setText("sys-log-file", info.log_file || "—");
    const monitor = byId("sys-monitor");
    if (monitor) monitor.title = info.monitor_error || "";
  }

  async function loadInterfaces(selected) {
    try {
      const data = await NW.api("/api/interfaces");
      interfaces = data.interfaces || [];
      populateInterfaces(selected);
    } catch (error) {
      NW.toast(error.message, "error", "Unable to load interfaces");
    }
  }

  async function loadSystem(showToast = false) {
    const button = byId("refresh-system");
    if (button) button.disabled = true;
    try {
      const info = await NW.api("/api/system/info");
      renderSystem(info);
      if (showToast) NW.toast("System information refreshed.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to read system information");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function load(showToast = false) {
    try {
      const [settings, interfaceData, info] = await Promise.all([
        NW.api("/api/settings"),
        NW.api("/api/interfaces"),
        NW.api("/api/system/info"),
      ]);
      interfaces = interfaceData.interfaces || [];
      populate(settings);
      renderSystem(info);
      NW.state.settings = settings;
      if (showToast) NW.toast("Settings reloaded from the database.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to load settings");
    }
  }

  function numberValue(id) {
    const element = byId(id);
    if (!element) return NaN;
    return Number(element.value);
  }

  function validate(payload) {
    const checks = [
      ["Download threshold", payload.download_threshold_mbps, 0, 100000],
      ["Upload threshold", payload.upload_threshold_mbps, 0, 100000],
      ["Alert cooldown", payload.alert_cooldown_seconds, 30, 3600],
      ["Retention", payload.retention_days, 1, 365],
      ["Refresh interval", payload.refresh_interval, 1, 30],
      ["Chart window", payload.chart_points, 20, 300],
      ["Discovery timeout", payload.discovery_timeout_ms, 100, 2000],
    ];
    for (const [label, value, minimum, maximum] of checks) {
      if (!Number.isFinite(value)) return `${label} must be a number.`;
      if (value < minimum || value > maximum) {
        return `${label} must be between ${minimum} and ${maximum}.`;
      }
    }
    if (payload.interface) {
      const names = interfaces.map((item) => item.name);
      if (!names.includes(payload.interface)) return "The selected interface no longer exists. Refresh and choose again.";
    }
    return null;
  }

  function collect() {
    return {
      refresh_interval: numberValue("setting-refresh"),
      interface: byId("setting-interface")?.value || "",
      chart_points: numberValue("setting-chart-points"),
      download_threshold_mbps: numberValue("setting-down-threshold"),
      upload_threshold_mbps: numberValue("setting-up-threshold"),
      alert_cooldown_seconds: numberValue("setting-cooldown"),
      retention_days: numberValue("setting-retention"),
      notifications_enabled: Boolean(byId("setting-notifications")?.checked),
      public_ip_enabled: Boolean(byId("setting-public-ip")?.checked),
      compact_mode: Boolean(byId("setting-compact")?.checked),
      discovery_timeout_ms: numberValue("setting-discovery-timeout"),
    };
  }

  function applyClientState(settings) {
    NW.state.settings = settings;
    document.body.classList.toggle("compact", Boolean(settings.compact_mode));
    document.dispatchEvent(new CustomEvent("nw:settings", { detail: settings }));
    NW.loadSummary(true).catch(() => {});
  }

  async function save(event) {
    event.preventDefault();
    const payload = collect();
    const problem = validate(payload);
    if (problem) {
      NW.toast(problem, "warning", "Check your settings");
      return;
    }
    const button = byId("save-settings");
    if (button) {
      button.disabled = true;
      button.dataset.original = button.innerHTML;
      button.textContent = "Saving…";
    }
    try {
      const settings = await NW.api("/api/settings", { method: "PUT", body: payload });
      populate(settings);
      applyClientState(settings);
      await loadSystem(false);
      NW.toast("Settings saved and applied to the monitoring engine.", "success", "Preferences updated");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to save settings");
    } finally {
      if (button) {
        button.disabled = false;
        if (button.dataset.original) button.innerHTML = button.dataset.original;
      }
    }
  }

  async function reset() {
    const confirmed = await NW.confirm({
      title: "Reset all settings",
      message:
        "Monitoring cadence, alert thresholds, retention, interface selection, and dashboard preferences return to their defaults. Recorded traffic, devices, and alerts are not deleted.",
      confirmLabel: "Reset defaults",
      danger: true,
    });
    if (!confirmed) return;
    const button = byId("reset-settings");
    if (button) button.disabled = true;
    try {
      const settings = await NW.api("/api/settings/reset", { method: "POST", body: {} });
      populate(settings);
      applyClientState(settings);
      await loadSystem(false);
      NW.toast("Settings restored to their defaults.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to reset settings");
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    byId("settings-form")?.addEventListener("submit", save);
    byId("reset-settings")?.addEventListener("click", reset);
    byId("refresh-system")?.addEventListener("click", () => loadSystem(true));
    document.addEventListener("nw:settings", (event) => {
      if (event.detail) {
        populate(event.detail);
      }
    });
    load();
  });
})();
