/* Interfaces — adapter inventory and primary adapter selection. */
(function () {
  "use strict";
  const NW = window.NW;

  function iconFor(type) {
    return { wifi: "wifi", virtual: "server", vpn: "shield", loopback: "refresh" }[type] || "interfaces";
  }

  function setText(id, value) {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  }

  function render(data) {
    setText("interface-count", data.count ?? 0);
    setText("interface-up-count", data.up_count ?? 0);
    setText("primary-interface", data.primary || "None");
    const primary = (data.interfaces || []).find((item) => item.name === data.primary);
    setText("interface-total", primary ? NW.byteString(primary.bytes_recv + primary.bytes_sent) : "—");

    const grid = document.getElementById("interface-grid");
    if (!grid) return;
    if (!data.interfaces?.length) {
      grid.innerHTML = `<div class="card"><div class="empty-state">${NW.icon("interfaces")}<p>No network adapters were detected by Windows.</p></div></div>`;
      return;
    }

    grid.innerHTML = data.interfaces
      .map((item) => {
        const selected = item.is_selected;
        const stateChip = `<span class="chip ${item.is_up ? "chip-live" : ""}"><span class="status-dot" data-state="${item.is_up ? "online" : "offline"}"></span>${item.is_up ? "Operational" : "Down"}</span>`;
        return `<article class="card interface-card ${item.is_primary ? "is-primary" : ""}">
          <div class="interface-head">
            <span class="adapter-icon ${item.is_up ? "is-up" : ""}">${NW.icon(iconFor(item.type))}</span>
            <div style="flex:1;min-width:0">
              <div class="interface-name">${NW.escape(item.name)}</div>
              <div class="interface-badges">
                ${stateChip}
                ${item.is_primary ? '<span class="chip">Primary</span>' : ""}
                ${selected ? '<span class="chip">Monitored</span>' : ""}
                <span class="chip">${NW.escape(item.type)}</span>
              </div>
            </div>
          </div>
          <div class="interface-body">
            <div class="spec-row"><span>IPv4</span><strong>${NW.escape(item.ipv4 || "—")}</strong></div>
            <div class="spec-row"><span>IPv6</span><strong>${NW.escape(item.ipv6 || "—")}</strong></div>
            <div class="spec-row"><span>MAC</span><strong>${NW.escape(item.mac || "—")}</strong></div>
            <div class="spec-row"><span>Link speed</span><strong>${item.link_speed_mbps ? `${item.link_speed_mbps} Mbps` : "Unknown"}</strong></div>
            <div class="spec-row"><span>MTU</span><strong>${item.mtu || "—"}</strong></div>
            <div class="spec-row"><span>Duplex</span><strong>${NW.escape(item.duplex || "unknown")}</strong></div>
            <div class="spec-row"><span>Received</span><strong>${NW.byteString(item.bytes_recv)}</strong></div>
            <div class="spec-row"><span>Sent</span><strong>${NW.byteString(item.bytes_sent)}</strong></div>
          </div>
          <div class="interface-actions">
            <span class="muted small">${NW.number(item.packets_recv)} packets in · ${NW.number(item.errors_in + item.errors_out)} errors · ${NW.number(item.drops_in + item.drops_out)} drops</span>
            ${
              selected
                ? '<button class="btn btn-ghost btn-sm" type="button" disabled>Monitoring</button>'
                : `<button class="btn btn-primary btn-sm" type="button" data-select="${NW.escape(item.name)}">Set as primary</button>`
            }
          </div>
        </article>`;
      })
      .join("");

    grid.querySelectorAll("[data-select]").forEach((button) => {
      button.addEventListener("click", () => selectInterface(button));
    });
  }

  async function selectInterface(button) {
    const name = button.dataset.select;
    button.disabled = true;
    button.textContent = "Applying…";
    try {
      const data = await NW.api("/api/interfaces/select", { method: "POST", body: { interface: name } });
      render(data);
      NW.toast(`Monitoring switched to ${name}.`, "success", "Interface selected");
      NW.loadSummary(true).catch(() => {});
    } catch (error) {
      button.disabled = false;
      button.textContent = "Set as primary";
      NW.toast(error.message, "error", "Unable to switch interface");
    }
  }

  async function load(showToast = false) {
    const button = document.getElementById("interfaces-refresh");
    if (button) button.disabled = true;
    try {
      const data = await NW.api("/api/interfaces");
      render(data);
      if (showToast) NW.toast("Adapter inventory refreshed.", "success");
    } catch (error) {
      NW.toast(error.message, "error", "Unable to read interfaces");
      const grid = document.getElementById("interface-grid");
      if (grid) grid.innerHTML = `<div class="card"><div class="empty-state">${NW.icon("warning")}<p>${NW.escape(error.message)}</p></div></div>`;
    } finally {
      if (button) button.disabled = false;
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("interfaces-refresh")?.addEventListener("click", () => load(true));
    load();
    setInterval(() => load(false), 30000);
    document.addEventListener("nw:settings", () => load(false));
  });
})();
