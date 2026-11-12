/* Diagnostics — validated ping, DNS, traceroute, and connectivity tools. */
(function () {
  "use strict";
  const NW = window.NW;

  function target() {
    const input = document.getElementById("diag-target");
    const value = (input?.value || "").trim();
    if (!value) {
      NW.toast("Enter a hostname or IP address first.", "warning");
      input?.focus();
      return null;
    }
    return value;
  }

  function setRunning(button, running, label) {
    if (!button) return;
    if (running) {
      button.dataset.original = button.innerHTML;
      button.disabled = true;
      button.textContent = label || "Running…";
    } else {
      button.disabled = false;
      if (button.dataset.original) button.innerHTML = button.dataset.original;
    }
  }

  function banner(container, text, type) {
    container.innerHTML = `<div class="status-banner ${type}">${NW.icon(type === "ok" ? "check" : type === "warn" ? "warning" : "warning")}${NW.escape(text)}</div>`;
  }

  async function runPing(button) {
    const host = target();
    if (!host) return;
    setRunning(button, true, "Pinging…");
    const result = document.getElementById("ping-result");
    const output = document.getElementById("ping-output");
    try {
      const data = await NW.api("/api/diagnostics/ping", { method: "POST", body: { host } });
      const average = data.avg_ms === null ? "—" : `${data.avg_ms} ms`;
      result.innerHTML = `
        <div class="status-banner ${data.success ? "ok" : "bad"}">${NW.icon(data.success ? "check" : "warning")}${data.success ? `Reply received from ${NW.escape(data.target)}` : `No reply from ${NW.escape(data.target)}`}</div>
        <div class="result-summary">
          <div class="result-stat"><span>Sent</span><strong>${data.sent}</strong></div>
          <div class="result-stat"><span>Received</span><strong>${data.received}</strong></div>
          <div class="result-stat"><span>Loss</span><strong>${data.loss_percent}%</strong></div>
          <div class="result-stat"><span>Average</span><strong>${average}</strong></div>
        </div>
        <div class="result-line"><span>Minimum / maximum</span><strong>${data.min_ms ?? "—"} / ${data.max_ms ?? "—"} ms</strong></div>
        <div class="result-line"><span>Execution time</span><strong>${data.duration_ms} ms</strong></div>`;
      if (output) {
        output.hidden = false;
        output.textContent = data.output || "No console output.";
      }
    } catch (error) {
      banner(result, error.message, "bad");
      if (output) output.hidden = true;
      NW.toast(error.message, "error", "Ping failed");
    } finally {
      setRunning(button, false);
    }
  }

  async function runDns(button) {
    const host = target();
    if (!host) return;
    setRunning(button, true, "Resolving…");
    const result = document.getElementById("dns-result");
    const recordType = document.getElementById("dns-record-type")?.value || "A";
    try {
      const data = await NW.api("/api/diagnostics/dns", {
        method: "POST",
        body: { host, record_type: recordType },
      });
      if (data.error) {
        result.innerHTML = `<div class="status-banner warn">${NW.icon("warning")}${NW.escape(data.error)}</div>
          <div class="result-line"><span>Nameserver</span><strong class="mono">${NW.escape(data.nameserver || "system default")}</strong></div>
          <div class="result-line"><span>Duration</span><strong>${data.duration_ms} ms</strong></div>`;
        return;
      }
      const records = (data.records || [])
        .map(
          (record) => `<div class="result-line"><span class="mono">${NW.escape(recordType)}</span><strong class="mono">${NW.escape(record)}</strong></div>`
        )
        .join("");
      result.innerHTML = `<div class="status-banner ok">${NW.icon("check")}${data.records.length} ${NW.escape(recordType)} record(s) resolved</div>${records}
        <div class="result-line"><span>Nameserver</span><strong class="mono">${NW.escape(data.nameserver || "system default")}</strong></div>
        <div class="result-line"><span>Duration</span><strong>${data.duration_ms} ms</strong></div>`;
    } catch (error) {
      banner(result, error.message, "bad");
      NW.toast(error.message, "error", "DNS lookup failed");
    } finally {
      setRunning(button, false);
    }
  }

  async function runTrace(button) {
    const host = target();
    if (!host) return;
    setRunning(button, true, "Tracing…");
    const result = document.getElementById("trace-result");
    const output = document.getElementById("trace-output");
    try {
      const data = await NW.api("/api/diagnostics/traceroute", { method: "POST", body: { host } });
      const hops = (data.hops || [])
        .map((hop) => {
          const times = hop.times_ms?.length ? hop.times_ms.map((time) => `${time} ms`).join(" · ") : "no response";
          return `<tr><td>${hop.hop}</td><td>${NW.escape(hop.ip || "*")}</td><td>${NW.escape(times)}</td></tr>`;
        })
        .join("");
      result.innerHTML = `
        <div class="status-banner ${data.timed_out ? "warn" : "ok"}">${NW.icon(data.timed_out ? "warning" : "check")}${data.timed_out ? "Trace timed out before completion" : `${data.hop_count} hops observed in ${data.duration_ms} ms`}</div>
        <table class="route-table"><thead><tr><th>#</th><th>Address</th><th>RTT</th></tr></thead><tbody>${hops || '<tr><td colspan="3">No hops parsed.</td></tr>'}</tbody></table>`;
      if (output) {
        output.hidden = false;
        output.textContent = data.output || "No console output.";
      }
    } catch (error) {
      banner(result, error.message, "bad");
      if (output) output.hidden = true;
      NW.toast(error.message, "error", "Traceroute failed");
    } finally {
      setRunning(button, false);
    }
  }

  async function runConnectivity(button) {
    setRunning(button, true, "Testing…");
    const result = document.getElementById("connectivity-result");
    try {
      const data = await NW.api("/api/diagnostics/connectivity");
      const targets = (data.targets || [])
        .map(
          (item) => `<div class="result-line">
            <span><span class="status-inline" data-state="${item.online ? "online" : "offline"}"><span class="status-dot"></span>${NW.escape(item.name)}</span></span>
            <strong>${item.online ? (item.latency_ms !== null ? `${item.latency_ms} ms` : "Reachable") : "Unreachable"}</strong>
          </div>`
        )
        .join("");
      result.innerHTML = `<div class="status-banner ${data.online ? "ok" : "bad"}">${NW.icon(data.online ? "check" : "warning")}${data.online ? "Outbound connectivity available" : "No outbound connectivity detected"}</div>${targets}
        <div class="result-line"><span>Test duration</span><strong>${data.duration_ms} ms</strong></div>`;
    } catch (error) {
      banner(result, error.message, "bad");
      NW.toast(error.message, "error", "Connectivity test failed");
    } finally {
      setRunning(button, false);
    }
  }

  const runners = {
    ping: runPing,
    dns: runDns,
    traceroute: runTrace,
    connectivity: runConnectivity,
  };

  function resetResults() {
    const empty = (icon, text) => `<div class="empty-state compact-empty">${NW.icon(icon)}<p>${text}</p></div>`;
    const mapping = {
      "ping-result": empty("activity", "Run a ping to measure reachability and latency."),
      "dns-result": empty("globe", "Resolve a hostname to inspect its DNS records."),
      "trace-result": empty("router", "Trace the path packets take to the target."),
      "connectivity-result": empty("wifi", "Test outbound connectivity against independent targets."),
    };
    Object.entries(mapping).forEach(([id, html]) => {
      const element = document.getElementById(id);
      if (element) element.innerHTML = html;
    });
    ["ping-output", "trace-output"].forEach((id) => {
      const element = document.getElementById(id);
      if (element) {
        element.hidden = true;
        element.textContent = "";
      }
    });
  }

  document.addEventListener("DOMContentLoaded", () => {
    NW.$$("[data-run]").forEach((button) => {
      button.addEventListener("click", () => runners[button.dataset.run]?.(button));
    });
    NW.$$("[data-target]").forEach((button) => {
      button.addEventListener("click", () => {
        const input = document.getElementById("diag-target");
        if (input) {
          input.value = button.dataset.target;
          input.focus();
        }
      });
    });
    document.getElementById("diag-target")?.addEventListener("keydown", (event) => {
      if (event.key === "Enter") {
        event.preventDefault();
        document.querySelector('[data-run="ping"]')?.click();
      }
    });
    document.getElementById("diagnostics-clear")?.addEventListener("click", () => {
      resetResults();
      NW.toast("Diagnostic results cleared.", "info");
    });
  });
})();
