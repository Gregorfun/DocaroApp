/**
 * Upload Progress Messages & Animations
 * Abwechslungsreiche Live-Ansicht mit Phasen, Ticker, Stats und Preview.
 */

const UploadMessages = {
  facts: [
    "OCR reagiert sensibel auf Scanqualitaet und Kontrast.",
    "Docaro kombiniert Textlayer, OCR, Regeln und Confidence.",
    "Klare Scans verbessern Lieferant und Dokumentnummer deutlich.",
    "Manuelle Korrekturen fliessen direkt in Trainingsdaten ein.",
    "Dokumenttypen steuern automatisch das Routing im Prozess.",
    "Dubletten werden automatisch erkannt und uebersprungen."
  ],

  motivational: [
    "Pipeline aktiv: der naechste Beleg wird bereits verarbeitet.",
    "Deine PDFs werden in strukturierte Daten umgewandelt.",
    "Fast geschafft: die letzten Schritte laufen.",
    "Routing, Review-Flags und Export werden gesetzt.",
    "Queue stabil - Verarbeitung laeuft sauber."
  ],

  jokes: [
    "Dokumentnummern verstecken sich gern in Zeile zwei.",
    "Lieferantennamen spielen gelegentlich Verstecken.",
    "Pixel-Detektive sichern gerade Beweisstuecke.",
    "Der OCR-Motor arbeitet heute mit Espresso-Modus.",
    "Wir fragen das PDF freundlich. Meistens antwortet es."
  ],

  animations: [
    "UPLOAD • RENDER • OCR • MATCH",
    "PDF • TEXT • FELDER • ERGEBNIS",
    "SCAN • ANALYSE • CONFIDENCE • READY",
    "QUEUE • WORKER • REVIEW • DONE"
  ],

  statsTemplates: [
    "Heute verarbeitet: {today}",
    "Wochendurchsatz: {count}",
    "Durchschnitt: {time}s / Dokument",
    "Gesamt: {total}",
    "Erfolgsquote: {rate}%"
  ],

  currentStats: {
    weekCount: 0,
    avgTime: 3.2,
    totalCount: 0,
    successRate: 95,
    todayCount: 0
  },

  getRandom(array) {
    if (!Array.isArray(array) || array.length === 0) {
      return "";
    }
    return array[Math.floor(Math.random() * array.length)];
  },

  getStats() {
    const template = this.getRandom(this.statsTemplates);
    const stats = this.currentStats;
    return template
      .replace('{count}', stats.weekCount || 0)
      .replace('{time}', Number(stats.avgTime || 0).toFixed(1))
      .replace('{total}', stats.totalCount || 0)
      .replace('{rate}', stats.successRate || 0)
      .replace('{today}', stats.todayCount || 0);
  },

  updateStats(stats) {
    if (stats && typeof stats === 'object') {
      Object.assign(this.currentStats, stats);
    }
  },

  async fetchStats() {
    try {
      const response = await fetch('/api/stats', { credentials: 'same-origin' });
      if (!response.ok) {
        return;
      }
      const data = await response.json();
      this.updateStats({
        weekCount: data.weekCount,
        avgTime: data.avgTime,
        totalCount: data.totalCount,
        successRate: data.successRate,
        todayCount: data.todayCount
      });
    } catch (_) {
      // optional endpoint
    }
  }
};

class Rotator {
  constructor(items) {
    this.items = Array.isArray(items) ? items.slice() : [];
    this.cursor = 0;
    this.last = "";
    this._reshuffle();
  }

  _reshuffle() {
    for (let i = this.items.length - 1; i > 0; i -= 1) {
      const j = Math.floor(Math.random() * (i + 1));
      const t = this.items[i];
      this.items[i] = this.items[j];
      this.items[j] = t;
    }
    this.cursor = 0;
  }

  next() {
    if (this.items.length === 0) {
      return "";
    }
    if (this.cursor >= this.items.length) {
      this._reshuffle();
    }
    let value = this.items[this.cursor] || "";
    this.cursor += 1;
    if (value === this.last && this.items.length > 1) {
      value = this.items[this.cursor % this.items.length];
      this.cursor += 1;
    }
    this.last = value;
    return value;
  }
}

class ProgressDisplay {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) return;

    this.messageEl = null;
    this.animationEl = null;
    this.progressEl = null;
    this.phaseEl = null;
    this.tickerEl = null;
    this.storyEl = null;
    this.liveStatsEl = null;
    this.qualityEl = null;
    this.completionEl = null;

    this.messageInterval = null;
    this.animationInterval = null;
    this.storyInterval = null;
    this.tickerInterval = null;
    this.statusTimer = null;
    this.statsTimer = null;
    this.finishTimer = null;
    this.sse = null;

    this.pollDelayMs = 2000;
    this.maxPollDelayMs = 10000;
    this.usingSse = false;
    this.latestPayload = null;
    this.finished = false;

    this.messageRotator = new Rotator([
      ...UploadMessages.facts,
      ...UploadMessages.motivational,
      ...UploadMessages.jokes,
      ...UploadMessages.statsTemplates
    ]);
    this.animationRotator = new Rotator(UploadMessages.animations);
    this.storyRotator = new Rotator([
      "Tipp: Klare, gerade Scans erhöhen die Trefferqualität deutlich.",
      "Info: Dubletten werden erkannt und nicht erneut verarbeitet.",
      "Hinweis: Niedrige Confidence wird automatisch priorisiert.",
      "Pro-Tipp: Supplier-Profile verbessern Doc-Type und Nummern-Extraktion.",
      "Pipeline: Routing-Tag und Review-Priorität werden live berechnet.",
      "Qualität: Manuelle Korrekturen werden als Ground-Truth gespeichert."
    ]);

    this.phases = [
      { id: 'queue', label: 'Queue' },
      { id: 'render', label: 'Render' },
      { id: 'ocr', label: 'OCR' },
      { id: 'extract', label: 'Felder' },
      { id: 'post', label: 'Sort/Review' },
      { id: 'done', label: 'Fertig' }
    ];

    this.init();
  }

  init() {
    this.container.innerHTML = `
      <div class="progress-display progress-display-rich">
        <div class="progress-phase" data-role="phase"></div>
        <div class="progress-animation" data-role="animation"></div>
        <div class="progress-message" data-role="message"></div>
        <div class="progress-ticker" data-role="ticker"></div>
        <div class="progress-bar-container" data-role="bar"></div>
        <div class="progress-live-grid">
          <div class="progress-card" data-role="story"></div>
          <div class="progress-card" data-role="live-stats"></div>
          <div class="progress-card" data-role="quality"></div>
        </div>
        <div class="progress-completion" data-role="completion" hidden></div>
      </div>
    `;

    this.phaseEl = this.container.querySelector('[data-role="phase"]');
    this.animationEl = this.container.querySelector('[data-role="animation"]');
    this.messageEl = this.container.querySelector('[data-role="message"]');
    this.tickerEl = this.container.querySelector('[data-role="ticker"]');
    this.progressEl = this.container.querySelector('[data-role="bar"]');
    this.storyEl = this.container.querySelector('[data-role="story"]');
    this.liveStatsEl = this.container.querySelector('[data-role="live-stats"]');
    this.qualityEl = this.container.querySelector('[data-role="quality"]');
    this.completionEl = this.container.querySelector('[data-role="completion"]');
  }

  start() {
    if (!this.container) return;

    this.updateAnimation();
    this.updateMessage();
    this.updateStory();
    this.updateTicker();

    this.animationInterval = setInterval(() => this.updateAnimation(), 2400);
    this.messageInterval = setInterval(() => this.updateMessage(), 4200);
    this.storyInterval = setInterval(() => this.updateStory(), 5200);
    this.tickerInterval = setInterval(() => this.updateTicker(), 3200);

    UploadMessages.fetchStats();
    this.statsTimer = setInterval(() => UploadMessages.fetchStats(), 15000);

    this.startLiveUpdates();
  }

  stop() {
    if (this.messageInterval) clearInterval(this.messageInterval);
    if (this.animationInterval) clearInterval(this.animationInterval);
    if (this.storyInterval) clearInterval(this.storyInterval);
    if (this.tickerInterval) clearInterval(this.tickerInterval);
    if (this.statusTimer) clearTimeout(this.statusTimer);
    if (this.statsTimer) clearInterval(this.statsTimer);
    if (this.finishTimer) clearTimeout(this.finishTimer);
    if (this.sse) {
      this.sse.close();
      this.sse = null;
    }
  }

  derivePhase(payload) {
    const progress = (payload && payload.progress) || {};
    const done = Number(progress.done || 0);
    const total = Number(progress.total || 0);
    const percent = total > 0 ? done / total : 0;
    const jobStatus = String(payload?.active_job_status || '').toLowerCase();

    if (!payload?.processing) return 'done';
    if (jobStatus.includes('queued') || jobStatus.includes('deferred') || done === 0) return 'queue';
    if (percent < 0.22) return 'render';
    if (percent < 0.58) return 'ocr';
    if (percent < 0.84) return 'extract';
    return 'post';
  }

  renderPhase(phaseId) {
    if (!this.phaseEl) return;
    const idx = this.phases.findIndex((p) => p.id === phaseId);
    this.phaseEl.innerHTML = this.phases
      .map((phase, i) => {
        const cls = i < idx ? 'done' : (i === idx ? 'active' : 'pending');
        return `<span class="phase-pill ${cls}">${phase.label}</span>`;
      })
      .join('');
  }

  updateAnimation() {
    if (!this.animationEl) return;
    this.animationEl.textContent = this.animationRotator.next();
    this.animationEl.classList.add('pulse');
    setTimeout(() => this.animationEl.classList.remove('pulse'), 500);
  }

  updateMessage() {
    if (!this.messageEl) return;
    const template = this.messageRotator.next();
    const text = template.includes('{') ? UploadMessages.getStats() : template;
    this.messageEl.textContent = text;
    this.messageEl.classList.add('fade-in');
    setTimeout(() => this.messageEl.classList.remove('fade-in'), 500);
  }

  updateStory() {
    if (!this.storyEl) return;
    this.storyEl.innerHTML = `<strong>Insight:</strong> ${this.storyRotator.next()}`;
  }

  updateTicker() {
    if (!this.tickerEl) return;
    const p = this.latestPayload || {};
    const progress = p.progress || {};
    const queueDepth = Number(p.queue_depth || 0);
    const file = String(progress.current_file || '').trim();
    const route = String(p.recent_result?.processing_route || '').trim();

    const lines = [
      file ? `Aktuelle Datei: ${file}` : 'Warte auf nächsten Verarbeitungsschritt.',
      `Queue-Länge: ${queueDepth}`,
      route ? `Routing: ${route}` : 'Routing wird ermittelt.'
    ];
    this.tickerEl.textContent = lines[Math.floor(Math.random() * lines.length)];
  }

  updateProgress(done, total) {
    if (!this.progressEl) return;

    if (total > 0) {
      const percent = Math.round((done / total) * 100);
      const currentFile = (window.docaroProgress && window.docaroProgress.current_file) ? window.docaroProgress.current_file : '';
      this.progressEl.innerHTML = `
        <progress value="${done}" max="${total}"></progress>
        <span class="progress-text">${done}/${total} - ${percent}%</span>
        ${currentFile ? `<div class="progress-current">Aktuell: <span>${currentFile}</span></div>` : ``}
      `;
    } else {
      this.progressEl.innerHTML = '<progress></progress>';
    }
  }

  updateLiveStats(payload) {
    if (!this.liveStatsEl) return;
    const queueDepth = Number(payload.queue_depth || 0);
    const totalResults = Number(payload.results_count || 0);
    const avgTime = Number(UploadMessages.currentStats.avgTime || 0).toFixed(1);
    const successRate = Number(UploadMessages.currentStats.successRate || 0);

    this.liveStatsEl.innerHTML = `
      <strong>Live-Stats</strong>
      <div>Queue: <span>${queueDepth}</span></div>
      <div>Ergebnisse: <span>${totalResults}</span></div>
      <div>Ø Dauer: <span>${avgTime}s</span></div>
      <div>Erfolg: <span>${successRate}%</span></div>
    `;
  }

  updateQualityPreview(payload) {
    if (!this.qualityEl) return;
    const recent = payload.recent_result || {};
    const supplier = String(recent.supplier || '-');
    const date = String(recent.date || '-');
    const docType = String(recent.doc_type || '-');
    const route = String(recent.processing_route || '-');
    const confidence = String(recent.supplier_confidence || '-');
    const review = recent.needs_review ? 'ja' : 'nein';

    this.qualityEl.innerHTML = `
      <strong>Vorschau letzter Treffer</strong>
      <div>Lieferant: <span>${supplier}</span></div>
      <div>Datum: <span>${date}</span></div>
      <div>Typ: <span>${docType}</span></div>
      <div>Route: <span>${route}</span></div>
      <div>Confidence: <span>${confidence}</span></div>
      <div>Review nötig: <span>${review}</span></div>
    `;
  }

  showCompletion() {
    if (!this.completionEl || this.finished) return;
    this.finished = true;

    this.completionEl.hidden = false;
    let remaining = 7;
    this.completionEl.innerHTML = `
      <div class="completion-title">Batch abgeschlossen</div>
      <div class="completion-actions">
        <button type="button" data-action="reload">Jetzt aktualisieren</button>
        <a href="/" data-action="home">Zur Übersicht</a>
      </div>
      <div class="completion-countdown">Automatische Aktualisierung in <span data-role="count">${remaining}</span>s</div>
    `;

    const countEl = this.completionEl.querySelector('[data-role="count"]');
    const reloadBtn = this.completionEl.querySelector('[data-action="reload"]');
    if (reloadBtn) {
      reloadBtn.addEventListener('click', () => window.location.reload());
    }

    const tick = () => {
      remaining -= 1;
      if (countEl) countEl.textContent = String(Math.max(remaining, 0));
      if (remaining <= 0) {
        window.location.reload();
        return;
      }
      this.finishTimer = setTimeout(tick, 1000);
    };
    this.finishTimer = setTimeout(tick, 1000);
  }

  handlePayload(payload) {
    if (!payload || payload.ok !== true) {
      return;
    }

    this.latestPayload = payload;

    const progress = payload.progress || {};
    const done = Number(progress.done || 0);
    const total = Number(progress.total || 0);
    const currentFile = String(progress.current_file || '');
    window.docaroProgress = { done, total, current_file: currentFile };

    if (total > 0) {
      this.updateProgress(done, total);
    }

    const phase = this.derivePhase(payload);
    this.renderPhase(phase);
    this.updateLiveStats(payload);
    this.updateQualityPreview(payload);
    this.updateTicker();

    if (!payload.processing) {
      this.stop();
      this.showCompletion();
    }
  }

  scheduleNextPoll(delayMs) {
    if (this.statusTimer) {
      clearTimeout(this.statusTimer);
    }
    this.statusTimer = setTimeout(() => this.pollStatus(), delayMs);
  }

  async pollStatus() {
    try {
      const response = await fetch('/status.json', {
        credentials: 'same-origin',
        headers: { Accept: 'application/json' }
      });
      const contentType = response.headers.get('content-type') || '';
      if (!response.ok || !contentType.includes('application/json')) {
        this.pollDelayMs = Math.min(Math.round(this.pollDelayMs * 1.4), this.maxPollDelayMs);
        this.scheduleNextPoll(this.pollDelayMs);
        return;
      }
      const payload = await response.json();
      this.pollDelayMs = 2000;
      this.handlePayload(payload);
      if (payload.processing) {
        this.scheduleNextPoll(this.pollDelayMs);
      }
    } catch (_) {
      this.pollDelayMs = Math.min(Math.round(this.pollDelayMs * 1.6), this.maxPollDelayMs);
      this.scheduleNextPoll(this.pollDelayMs);
    }
  }

  startSse() {
    if (!window.EventSource) {
      return false;
    }
    try {
      this.sse = new EventSource('/status.stream');
      this.usingSse = true;
      this.sse.onmessage = (event) => {
        try {
          const payload = JSON.parse(event.data || '{}');
          this.handlePayload(payload);
        } catch (_) {
          // ignore malformed frame
        }
      };
      this.sse.onerror = () => {
        if (this.sse) {
          this.sse.close();
          this.sse = null;
        }
        this.usingSse = false;
        this.scheduleNextPoll(this.pollDelayMs);
      };
      return true;
    } catch (_) {
      this.usingSse = false;
      return false;
    }
  }

  startLiveUpdates() {
    if (!this.startSse()) {
      this.scheduleNextPoll(this.pollDelayMs);
    }
  }
}

// Auto-Init wenn Verarbeitung läuft
document.addEventListener('DOMContentLoaded', () => {
  const processingNotice = document.querySelector('.processing-notice');
  if (!processingNotice) {
    return;
  }

  UploadMessages.fetchStats().then(() => {
    const display = new ProgressDisplay('progress-enhanced');
    display.start();

    const progressData = window.docaroProgress || {};
    if (Number(progressData.total || 0) > 0) {
      display.updateProgress(Number(progressData.done || 0), Number(progressData.total || 0));
    }
    display.renderPhase('queue');
  });
});
