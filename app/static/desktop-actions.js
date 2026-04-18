/**
 * DocaroApp Desktop Komfort-Helfer:
 * - Native Toast-Benachrichtigungen (nur Desktop-EXE)
 * - "Im Explorer zeigen"-Aufruf
 * - Recent-Files-Speicher
 *
 * Im Web-Modus sind die Endpunkte deaktiviert; alle Helfer schlucken Fehler still.
 */
(function () {
  "use strict";

  const RUNTIME_INFO_URL = "/api/desktop/info";
  let cachedInfo = null;
  let infoPromise = null;

  function getCsrfToken() {
    const meta = document.querySelector('meta[name="csrf-token"]');
    if (meta && meta.content) return meta.content;
    const m = document.cookie.match(/(?:^|; )XSRF-TOKEN=([^;]+)/);
    return m ? decodeURIComponent(m[1]) : "";
  }

  async function fetchJson(url, options) {
    const opts = Object.assign({ credentials: "same-origin" }, options || {});
    opts.headers = Object.assign({}, opts.headers || {}, {
      "X-CSRF-Token": getCsrfToken(),
      Accept: "application/json",
    });
    if (opts.body && typeof opts.body === "object" && !(opts.body instanceof FormData)) {
      opts.headers["Content-Type"] = "application/json";
      opts.body = JSON.stringify(opts.body);
    }
    const resp = await fetch(url, opts);
    let payload = null;
    try {
      payload = await resp.json();
    } catch (_) {
      payload = null;
    }
    return { ok: resp.ok, status: resp.status, data: payload };
  }

  function getRuntimeInfo() {
    if (cachedInfo) return Promise.resolve(cachedInfo);
    if (infoPromise) return infoPromise;
    infoPromise = fetchJson(RUNTIME_INFO_URL)
      .then((res) => {
        cachedInfo = (res.ok && res.data) ? res.data : { desktop_mode: false, offline: true };
        return cachedInfo;
      })
      .catch(() => {
        cachedInfo = { desktop_mode: false, offline: true };
        return cachedInfo;
      });
    return infoPromise;
  }

  async function isDesktop() {
    const info = await getRuntimeInfo();
    return Boolean(info && info.desktop_mode);
  }

  async function reveal(path) {
    if (!path) return false;
    if (!(await isDesktop())) return false;
    try {
      const res = await fetchJson("/api/desktop/reveal", {
        method: "POST",
        body: { path: path },
      });
      return Boolean(res.ok && res.data && res.data.ok);
    } catch (_) {
      return false;
    }
  }

  async function notify(title, body) {
    if (!(await isDesktop())) return false;
    try {
      const res = await fetchJson("/api/desktop/notify", {
        method: "POST",
        body: { title: title || "DocaroApp", body: body || "" },
      });
      return Boolean(res.ok && res.data && res.data.ok);
    } catch (_) {
      return false;
    }
  }

  async function addRecent(entry) {
    if (!entry || !entry.kind || !entry.filename) return false;
    try {
      const res = await fetchJson("/api/desktop/recent", {
        method: "POST",
        body: entry,
      });
      return Boolean(res.ok && res.data && res.data.ok);
    } catch (_) {
      return false;
    }
  }

  async function loadRecent() {
    try {
      const res = await fetchJson("/api/desktop/recent");
      if (res.ok && res.data && Array.isArray(res.data.items)) return res.data.items;
    } catch (_) {}
    return [];
  }

  async function clearRecent() {
    try {
      const res = await fetchJson("/api/desktop/recent/clear", { method: "POST" });
      return Boolean(res.ok && res.data && res.data.ok);
    } catch (_) {
      return false;
    }
  }

  function downloadDiagnosticsZip() {
    const link = document.createElement("a");
    link.href = "/api/desktop/diagnostics.zip";
    link.rel = "noopener";
    document.body.appendChild(link);
    link.click();
    setTimeout(() => link.remove(), 0);
  }

  async function loadPrefs() {
    try {
      const res = await fetchJson("/api/desktop/prefs");
      if (res.ok && res.data && res.data.prefs) return res.data.prefs;
    } catch (_) {}
    return null;
  }

  async function savePref(changes) {
    if (!changes || typeof changes !== "object") return false;
    try {
      const res = await fetchJson("/api/desktop/prefs", { method: "POST", body: changes });
      return Boolean(res.ok && res.data && res.data.ok);
    } catch (_) {
      return false;
    }
  }

  function showOfflineBadgeWhenReady() {
    document.querySelectorAll('[data-offline-badge]').forEach((el) => {
      el.hidden = false;
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    showOfflineBadgeWhenReady();
    getRuntimeInfo().then((info) => {
      document.body.dataset.desktopMode = info && info.desktop_mode ? "1" : "0";
      // Reveal-Buttons im Desktop-Modus aktivieren
      document.querySelectorAll('[data-desktop-only]').forEach((el) => {
        el.hidden = !(info && info.desktop_mode);
      });
    });

    document.addEventListener("click", async function (event) {
      const target = event.target.closest("[data-reveal-path]");
      if (target) {
        event.preventDefault();
        const path = target.getAttribute("data-reveal-path");
        const ok = await reveal(path);
        if (!ok) {
          target.classList.add("reveal-failed");
          setTimeout(() => target.classList.remove("reveal-failed"), 1500);
        }
        return;
      }
      const diag = event.target.closest("[data-diagnose-export]");
      if (diag) {
        event.preventDefault();
        downloadDiagnosticsZip();
      }
    });
  });

  window.DocaroDesktop = {
    info: getRuntimeInfo,
    isDesktop,
    reveal,
    notify,
    addRecent,
    loadRecent,
    clearRecent,
    downloadDiagnosticsZip,
    loadPrefs,
    savePref,
  };
})();
