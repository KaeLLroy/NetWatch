/* Alerts — event timeline, acknowledgement, and history management. */
(function () {
  "use strict";
  const NW = window.NW;

  let alerts = [];
  let filter = "all";
  let loading = false;

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  function visibleAlerts() {
    return filter === "unread" ? alerts.filter((alert) => !alert.acknowledged) : alerts;
  }

  function severityIcon(severity) {
    if (severity === "critical") return "warning";
    if (severity === "warning") return "activity";
    return "info";
  }

  function renderStats() {
    const unread = alerts.filter((alert) => !alert.acknowledged).length;
    const critical = alerts.filter((alert) => alert.severity === "critical").length;
    const warning = alerts.filter((alert) => alert.severity === "warning").length;
    const info = alerts.filter((alert) => alert.severity === "info").length;
    setText("alerts-unread-count", unread);
    setText("alerts-critical-count", critical);
    setText("alerts-warning-count", warning);
    setText("alerts-info-count", info);
    NW.updateBadge(unread);
  }

  function renderList() {
    const container = document.getElementById("alerts-list");
    if (!container) return;
    const rows = visibleAlerts();
    setText("alerts-total-chip", `${rows.length} event${rows.length === 1 ? "" : "s"}`);
    setText(
      "alerts-subtitle",
      filter === "unread" ? "Unread events, newest first" : "Newest events first"
    );
    if (!rows.length) {
      container.innerHTML = `<div class="empty-state">${NW.icon("shield")}<p>${
        filter === "unread"
          ? "No unread alerts. Every event has been acknowledged."
          : "No alerts recorded yet. Connectivity transitions, adapter availability, and threshold breaches will appear here."
      }</p></div>`;
      return;
    }
    container.innerHTML = rows
      .map((alert) => {
        const severity = ["critical", "warning", "info"].includes(alert.severity)
          ? alert.severity
          : "info";
        const label = String(alert.type || "event").replaceAll("_", " ");
        return `<div class="alert-item ${alert.acknowledged ? "" : "is-unread"}">
          <span class="alert-icon severity-${severity}">${NW.icon(severityIcon(severity))}</span>
          <div class="alert-body">
            <p class="alert-message">${NW.escape(alert.message)}</p>
            <div class="alert-meta">
              <span class="alert-type">${NW.escape(label)}</span>
              <span>${NW.dateTime(alert.ts)}</span>
              <span>${NW.relative(alert.ts)}</span>
              ${alert.acknowledged ? "" : '<span class="status-inline" data-state="checking">Unread</span>'}
            </div>
          </div>
          <div class="alert-actions">
            ${
              alert.acknowledged
                ? '<span class="chip">Read</span>'
                : `<button class="btn btn-ghost btn-sm" type="button" data-ack="${alert.id}" title="Acknowledge alert">${NW.icon("check")} Mark read</button>`
            }
          </div>
        </div>`;
      })
      .join("");

    container.querySelectorAll("[data-ack]").forEach((button) => {
      button.addEventListener("click", () => acknowledge(Number(button.dataset.ack), button));
    });
  }

  function render() {
    renderStats();
    renderList();
  }

  async function load(showToast = false) {
    if (loading) return;
    loading = true;
    try {
      const data = await NW.api("/api/alerts?limit=500");
      alerts = data.alerts || [];
      render();
      if (showToast) NW.toast("Alert history refreshed.", "success");
    } catch (error) {
      const container = document.getElementById("alerts-list");
      if (container) {
        container.innerHTML = `<div class="empty-state">${NW.icon("warning")}<p>${NW.escape(error.message)}</p></div>`;
      }
      NW.toast(error.message, "error", "Unable to load alerts");
    } finally {
      loading = false;
    }
  }

  async function acknowledge(alertId, button) {
    if (!alertId) return;
    if (button) {
      button.disabled = true;
      button.textContent = "Saving…";
    }
    try {
      const result = await NW.api(`/api/alerts/${alertId}/ack`, { method: "POST", body: {} });
      const record = alerts.find((alert) => alert.id === alertId);
      if (record) record.acknowledged = 1;
      NW.updateBadge(result.unread);
      render();
      NW.toast("Alert marked as read.", "success");
    } catch (error) {
      if (button) {
        button.disabled = false;
        button.innerHTML = `${NW.icon("check")} Mark read`;
      }
      NW.toast(error.message, "error", "Unable to acknowledge alert");
    }
  }

  async function acknowledgeAll() {
    const unread = alerts.filter((alert) => !alert.acknowledged).length;
    if (!unread) {
      NW.toast("There are no unread alerts.", "info");
      return;
    }
    const button = document.getElementById("alerts-ack-all");
    if (button) button.disabled = true;
    try {
      const result = await NW.api("/api/alerts/ack-all", { method: "POST", body: {} });
      alerts = alerts.map((alert) => ({ ...alert, acknowledged: 1 }));
      NW.updateBadge(result.unread);
      render();
      NW.toast(`${result.acknowledged} alert(s) marked as read.`, "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to update alerts");
    } finally {
      if (button) button.disabled = false;
    }
  }

  async function clearAll() {
    if (!alerts.length) {
      NW.toast("There is no alert history to clear.", "info");
      return;
    }
    const confirmed = await NW.confirm({
      title: "Clear alert history",
      message:
        "This permanently removes every alert from the local database. Monitoring continues and future events will still be recorded.",
      confirmLabel: "Clear history",
      danger: true,
    });
    if (!confirmed) return;
    const button = document.getElementById("alerts-clear");
    if (button) button.disabled = true;
    try {
      const result = await NW.api("/api/alerts/clear", { method: "POST", body: {} });
      alerts = [];
      NW.updateBadge(0);
      render();
      NW.toast(`${result.deleted} alert(s) removed from history.`, "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to clear alerts");
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    NW.$$("#alert-filter button").forEach((button) => {
      button.addEventListener("click", () => {
        filter = button.dataset.filter || "all";
        NW.$$("#alert-filter button").forEach((item) =>
          item.classList.toggle("is-active", item === button)
        );
        renderList();
      });
    });
    document.getElementById("alerts-ack-all")?.addEventListener("click", acknowledgeAll);
    document.getElementById("alerts-clear")?.addEventListener("click", clearAll);
    document.addEventListener("nw:alert", () => load());
    document.addEventListener("nw:alerts-updated", () => load());
    load();
    setInterval(() => {
      if (!document.hidden) renderList();
    }, 30000);
  });
})();
