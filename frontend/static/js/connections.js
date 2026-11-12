/* Connections — live TCP session inventory. */
(function () {
  "use strict";
  const NW = window.NW;

  let rows = [];
  let auto = true;
  let timer = null;
  let search = "";

  const setText = (id, value) => {
    const element = document.getElementById(id);
    if (element) element.textContent = value;
  };

  function stateClass(state) {
    return `conn-state is-${String(state || "").toLowerCase().replaceAll(" ", "_")}`;
  }

  function renderTable() {
    const body = document.getElementById("connection-table-body");
    if (!body) return;
    const query = search.trim().toLowerCase();
    const filtered = rows.filter((row) =>
      [row.process, row.pid, row.local, row.remote, row.state].some((value) =>
        String(value ?? "").toLowerCase().includes(query)
      )
    );
    setText("connections-subtitle", `${filtered.length} visible sessions · local and remote endpoints`);
    if (!filtered.length) {
      body.innerHTML = `<tr><td colspan="6" class="table-empty">No connections match the current filter.</td></tr>`;
      return;
    }
    body.innerHTML = filtered
      .map(
        (row) => `<tr>
          <td><span class="process-name"><span class="process-dot"></span>${NW.escape(row.process || "Unknown process")}</span></td>
          <td class="num">${row.pid ?? "—"}</td>
          <td class="mono">${NW.escape(row.local || "—")}</td>
          <td class="mono">${NW.escape(row.remote || "—")}</td>
          <td><span class="${stateClass(row.state)}">${NW.escape(row.state)}</span></td>
          <td>${NW.escape(row.family)}</td>
        </tr>`
      )
      .join("");
  }

  function renderCounts(counts = {}) {
    setText("connections-established", counts.ESTABLISHED || 0);
    setText("connections-listening", counts.LISTEN || 0);
    setText("connections-timewait", counts.TIME_WAIT || 0);
    setText("connections-total", Object.values(counts).reduce((sum, value) => sum + Number(value || 0), 0));
  }

  async function load(showToast = false) {
    const button = document.getElementById("connections-refresh");
    if (button) button.disabled = true;
    const state = document.getElementById("connection-state")?.value || "all";
    try {
      const data = await NW.api(`/api/connections?state=${encodeURIComponent(state)}`);
      rows = data.connections || [];
      renderCounts(data.counts || {});
      renderTable();
      const banner = document.getElementById("connections-restricted");
      if (banner) banner.hidden = !data.restricted;
      if (data.message) setText("connections-restricted-message", data.message);
      setText("connections-updated", `Updated ${NW.time(data.timestamp)}`);
      if (showToast) NW.toast("Connection table refreshed.", "success");
    } catch (error) {
      setText("connections-updated", "Update failed");
      NW.toast(error.message, "error", "Unable to read connections");
    } finally {
      if (button) button.disabled = false;
    }
  }

  function schedule() {
    if (timer) clearInterval(timer);
    if (!auto) return;
    timer = setInterval(() => {
      if (!document.hidden) load(false);
    }, 5000);
  }

  document.addEventListener("DOMContentLoaded", () => {
    document.getElementById("connections-refresh")?.addEventListener("click", () => load(true));
    document.getElementById("connection-state")?.addEventListener("change", () => load(false));
    document.getElementById("connection-search")?.addEventListener(
      "input",
      NW.debounce((event) => {
        search = event.target.value;
        renderTable();
      }, 120)
    );
    document.getElementById("auto-refresh")?.addEventListener("change", (event) => {
      auto = event.target.checked;
      schedule();
      NW.toast(auto ? "Auto-refresh enabled." : "Auto-refresh paused.", "info");
    });
    load();
    schedule();
  });
})();
