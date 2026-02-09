// Theme Toggle Script für Dark/Light Mode
(function() {
  'use strict';

  // Konstanten
  const DARK_MODE_KEY = 'docaro-dark-mode';
  const HTML_ELEMENT = document.documentElement;
  const BUTTON_ID = 'theme-toggle-btn';
  
  // Initialisierung: Gespeicherte Einstellung laden oder System-Präferenz nutzen
  function initializeTheme() {
    let isDarkMode = localStorage.getItem(DARK_MODE_KEY);
    
    // Wenn keine Einstellung gespeichert ist, System-Präferenz nutzen
    if (isDarkMode === null) {
      isDarkMode = window.matchMedia('(prefers-color-scheme: dark)').matches;
    } else {
      isDarkMode = isDarkMode === 'true';
    }
    
    applyTheme(isDarkMode);
  }
  
  // Tema anwenden
  function applyTheme(isDarkMode) {
    if (isDarkMode) {
      HTML_ELEMENT.classList.add('dark-mode');
    } else {
      HTML_ELEMENT.classList.remove('dark-mode');
    }
    
    updateButtonIcon(isDarkMode);
  }
  
  // Button-Icon aktualisieren
  function updateButtonIcon(isDarkMode) {
    const button = document.getElementById(BUTTON_ID);
    if (button) {
      if (isDarkMode) {
        button.innerHTML = '☀️';
        button.title = 'Hellmodus aktivieren';
        button.setAttribute('aria-label', 'Hellmodus aktivieren');
      } else {
        button.innerHTML = '🌙';
        button.title = 'Dunkelmodus aktivieren';
        button.setAttribute('aria-label', 'Dunkelmodus aktivieren');
      }
    }
  }
  
  // Toggle-Funktionalität
  function toggleTheme() {
    const isDarkMode = HTML_ELEMENT.classList.contains('dark-mode');
    const newMode = !isDarkMode;
    
    localStorage.setItem(DARK_MODE_KEY, newMode ? 'true' : 'false');
    applyTheme(newMode);
  }
  
  // Event Listener registrieren
  function setupEventListeners() {
    const button = document.getElementById(BUTTON_ID);
    if (button) {
      button.addEventListener('click', toggleTheme);
    }
    
    // System-Präferenzänderung beobachten
    window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', (e) => {
      // Nur anwenden, wenn keine Benutzereinstellung gespeichert ist
      if (localStorage.getItem(DARK_MODE_KEY) === null) {
        applyTheme(e.matches);
      }
    });
    
    // Änderungen in anderen Tabs/Fenstern synchronisieren
    window.addEventListener('storage', (e) => {
      if (e.key === DARK_MODE_KEY) {
        const isDarkMode = e.newValue === 'true';
        applyTheme(isDarkMode);
      }
    });
  }
  
  // Beim Laden der Seite initialisieren
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', () => {
      initializeTheme();
      setupEventListeners();
    });
  } else {
    initializeTheme();
    setupEventListeners();
  }
})();
