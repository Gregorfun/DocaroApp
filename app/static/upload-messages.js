/**
 * Upload Progress Messages & Animations
 * Kombination aus Fakten, Witzen, Motivationssprüchen und Animationen
 */

const UploadMessages = {
  // OCR-Fakten
  facts: [
    "Wusstest du, dass OCR-Software manchmal 'l' und '1' verwechselt? Wir auch! 😅",
    "OCR steht für 'Optical Character Recognition' - quasi Zauberei mit Buchstaben! ✨",
    "Tesseract wurde ursprünglich von HP entwickelt und ist jetzt Open Source 🤓",
    "Moderne OCR-Systeme können über 100 Sprachen erkennen! 🌍",
    "Die erste OCR-Maschine wurde 1914 patentiert - über 100 Jahre alt! 📜",
    "OCR kann sogar handgeschriebene Texte lesen - aber deine Unterschrift bleibt sicher! 🖊️"
  ],

  // Motivierende Sprüche
  motivational: [
    "Geduld bitte, wir trainieren gerade unsere KI... nur Spaß, OCR läuft! 🚀",
    "Deine PDFs werden gerade in Textgold verwandelt! ⚡",
    "Gleich geschafft! Unsere Pixel-Detektive sind am Werk 🔍",
    "Rom wurde nicht an einem Tag erbaut - aber deine PDFs sind gleich fertig! 🏛️",
    "Kaffee holen? Nein, so schnell sind wir! ☕",
    "Schneller als du 'OCR' sagen kannst... fast! 🏃"
  ],

  // Loading-Witze (Job-spezifisch)
  jokes: [
    "Suche nach versteckten Rechnungsnummern... 🔍",
    "Überrede Lieferantennamen sich zu offenbaren... 💼",
    "Datumsjäger im Einsatz... 📅",
    "Tesseract macht Überstunden... 👓",
    "Pixel für Pixel wird analysiert... 🔬",
    "KI verhandelt mit deinen PDFs... 🤖",
    "Dokumente werden freundlich befragt... 📄",
    "Zahlen und Buchstaben sortieren sich... 🔤",
    "Daten-Detektive ermitteln... 🕵️",
    "OCR-Magie wird durchgeführt... 🪄",
    "Lieferscheine werden verhört... 📋",
    "Rechnungsdaten kapitulieren... 💰",
    "Textmuster werden enttarnt... 🎭",
    "PDF-Geheimnisse werden gelüftet... 🔓"
  ],

  // Animation Frames (Emoji-basiert)
  animations: [
    "📄 → 🔍 → 🤖 → ✅",
    "📎 → 📊 → 💾 → 🎉",
    "🗂️ → 🔎 → 📝 → ✨",
    "📃 → 👁️ → 🧠 → 🎯"
  ],

  // Statistik-Templates
  statsTemplates: [
    "Bereits {count} PDFs verarbeitet diese Woche! 📈",
    "Durchschnittliche Verarbeitungszeit: {time} Sekunden ⚡",
    "Gesamt verarbeitete Dokumente: {total} 📚",
    "Erfolgsquote: {rate}% - Spitzenklasse! 🏆",
    "Heute schon {today} Dokumente analysiert! 📊"
  ],

  // Aktuelle Statistiken (werden vom Server aktualisiert)
  currentStats: {
    weekCount: 0,
    avgTime: 3.2,
    totalCount: 0,
    successRate: 95,
    todayCount: 0
  },

  /**
   * Gibt einen zufälligen Text aus einem Array zurück
   */
  getRandom(array) {
    return array[Math.floor(Math.random() * array.length)];
  },

  /**
   * Gibt eine formatierte Statistik zurück
   */
  getStats() {
    const template = this.getRandom(this.statsTemplates);
    const stats = this.currentStats;

    return template
      .replace('{count}', stats.weekCount || Math.floor(Math.random() * 500) + 100)
      .replace('{time}', stats.avgTime.toFixed(1))
      .replace('{total}', stats.totalCount || Math.floor(Math.random() * 5000) + 1000)
      .replace('{rate}', stats.successRate)
      .replace('{today}', stats.todayCount || Math.floor(Math.random() * 50) + 10);
  },

  /**
   * Gibt eine zufällige Message zurück (Mix aus allem)
   */
  getRandomMessage() {
    const types = ['fact', 'motivational', 'joke', 'stats'];
    const type = types[Math.floor(Math.random() * types.length)];

    switch(type) {
      case 'fact':
        return this.getRandom(this.facts);
      case 'motivational':
        return this.getRandom(this.motivational);
      case 'joke':
        return this.getRandom(this.jokes);
      case 'stats':
        return this.getStats();
      default:
        return this.getRandom(this.jokes);
    }
  },

  /**
   * Aktualisiert Statistiken vom Server
   */
  updateStats(stats) {
    if (stats) {
      Object.assign(this.currentStats, stats);
    }
  },

  /**
   * Lädt aktuelle Statistiken vom Server
   */
  async fetchStats() {
    try {
      const response = await fetch('/api/stats', {
        credentials: 'same-origin'  // Include cookies for auth
      });
      if (response.ok) {
        const data = await response.json();
        this.updateStats({
          weekCount: data.weekCount,
          avgTime: data.avgTime,
          totalCount: data.totalCount,
          successRate: data.successRate,
          todayCount: data.todayCount
        });
      }
    } catch (error) {
      console.warn('Could not fetch stats:', error);
      // Fallback auf generierte Daten - kein Problem
    }
  }
};

/**
 * Progress Display Manager
 * Verwaltet die animierte Anzeige während des Upload-Prozesses
 */
class ProgressDisplay {
  constructor(containerId) {
    this.container = document.getElementById(containerId);
    if (!this.container) return;

    this.messageEl = null;
    this.animationEl = null;
    this.progressEl = null;
    this.messageInterval = null;
    this.animationInterval = null;
    this.statusTimer = null;
    this.statsTimer = null;
    this.sse = null;
    this.pollDelayMs = 2000;
    this.maxPollDelayMs = 10000;
    this.usingSse = false;
    this.animationFrame = 0;

    this.init();
  }

  init() {
    // Erstelle die Display-Elemente
    this.container.innerHTML = `
      <div class="progress-display">
        <div class="progress-animation"></div>
        <div class="progress-message"></div>
        <div class="progress-bar-container"></div>
      </div>
    `;

    this.animationEl = this.container.querySelector('.progress-animation');
    this.messageEl = this.container.querySelector('.progress-message');
    this.progressEl = this.container.querySelector('.progress-bar-container');
  }

  start() {
    if (!this.container) return;

    // Starte Animation Loop
    this.updateAnimation();
    this.animationInterval = setInterval(() => this.updateAnimation(), 2000);

    // Starte Message Loop
    this.updateMessage();
    this.messageInterval = setInterval(() => this.updateMessage(), 4000);
    UploadMessages.fetchStats();
    this.statsTimer = setInterval(() => UploadMessages.fetchStats(), 15000);

    // Bevorzugt SSE, fällt bei Bedarf auf Polling mit Backoff zurück.
    this.startLiveUpdates();
  }

  stop() {
    if (this.messageInterval) clearInterval(this.messageInterval);
    if (this.animationInterval) clearInterval(this.animationInterval);
    if (this.statusTimer) clearTimeout(this.statusTimer);
    if (this.statsTimer) clearInterval(this.statsTimer);
    if (this.sse) {
      this.sse.close();
      this.sse = null;
    }
  }

  updateAnimation() {
    if (!this.animationEl) return;
    const animation = UploadMessages.getRandom(UploadMessages.animations);
    this.animationEl.textContent = animation;
    this.animationEl.classList.add('pulse');
    setTimeout(() => this.animationEl.classList.remove('pulse'), 500);
  }

  updateMessage() {
    if (!this.messageEl) return;
    const message = UploadMessages.getRandomMessage();
    this.messageEl.textContent = message;
    this.messageEl.classList.add('fade-in');
    setTimeout(() => this.messageEl.classList.remove('fade-in'), 500);
  }

  updateProgress(done, total) {
    if (!this.progressEl) return;

    if (total > 0) {
      const percent = Math.round((done / total) * 100);
      const currentFile = (window.docaroProgress && window.docaroProgress.current_file) ? window.docaroProgress.current_file : "";
      this.progressEl.innerHTML = `
        <progress value="${done}" max="${total}"></progress>
        <span class="progress-text">${done}/${total} - ${percent}%</span>
        ${currentFile ? `<div class="progress-current">Aktuell: <span>${currentFile}</span></div>` : ``}
      `;
    } else {
      this.progressEl.innerHTML = '<progress></progress>';
    }
  }

  handlePayload(payload) {
    if (!payload || payload.ok !== true) {
      return;
    }
    const progress = payload.progress || {};
    const done = Number(progress.done || 0);
    const total = Number(progress.total || 0);
    const currentFile = String(progress.current_file || '');
    window.docaroProgress = { done, total, current_file: currentFile };
    if (total > 0) {
      this.updateProgress(done, total);
    }
    if (!payload.processing) {
      this.stop();
      window.location.reload();
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
      this.scheduleNextPoll(this.pollDelayMs);
    } catch (_) {
      // Netzwerk-/Auth-Fehler: Backoff bis max. 10s.
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
  if (processingNotice) {
    // Lade erst Statistiken, dann starte Display
    UploadMessages.fetchStats().then(() => {
      const display = new ProgressDisplay('progress-enhanced');
      display.start();

      // Extrahiere Progress-Werte aus dem Template-Kontext
      const progressData = window.docaroProgress || {};
      if (progressData.total > 0) {
        display.updateProgress(progressData.done || 0, progressData.total);
      }
    });
  }
});
