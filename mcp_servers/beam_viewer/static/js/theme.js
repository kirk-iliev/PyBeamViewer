"use strict";

/**
 * Theme toggle — dark / light, matching Qt gui/theme.py DARK & LIGHT.
 *
 * Persists choice to localStorage. Calls POST /display/theme/toggle to
 * keep the server in sync (best-effort).
 */

var ThemeManager = (function() {
  var STORAGE_KEY = "pybeamviewer-theme";
  var btn = document.getElementById("themeToggle");

  function currentTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  function apply(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    localStorage.setItem(STORAGE_KEY, theme);
    if (btn) {
      btn.textContent = theme === "dark" ? "\u2600  Light" : "\uD83C\uDF19  Dark";
    }
  }

  function toggle() {
    var next = currentTheme() === "dark" ? "light" : "dark";
    apply(next);
    // Notify the server (best-effort, headless mode is a no-op)
    fetch("../display/theme/toggle", { method: "POST" }).catch(function() {});
  }

  function init() {
    var saved = localStorage.getItem(STORAGE_KEY);
    apply(saved || "dark");
    if (btn) {
      btn.addEventListener("click", toggle);
    }
  }

  return { init: init, toggle: toggle, current: currentTheme };
})();
