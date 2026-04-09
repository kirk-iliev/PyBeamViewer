"use strict";

/**
 * Error state UI -- disconnection banner, fit-failure messages,
 * and no-camera empty state.
 *
 * Polls /health every 5 s to detect EPICS disconnection.
 * Checks WebSocket analysis payloads for null fit parameters.
 *
 * Exports:
 *   ErrorStates.init()
 *   ErrorStates.showDisconnected()
 *   ErrorStates.hideDisconnected()
 *   ErrorStates.showFitFailed(axis)   -- axis: "x" | "y"
 *   ErrorStates.hideFitFailed(axis)
 *   ErrorStates.showNoCameraState()
 *   ErrorStates.hideNoCameraState()
 *   ErrorStates.checkAnalysis(msg)    -- call from frame handler
 */

var ErrorStates = (function() {

  var HEALTH_INTERVAL = 5000; // 5 s
  var API_BASE = "..";

  // DOM refs (set in init)
  var disconnectedBanner = null;
  var noCameraBanner = null;
  var hFitFailedEl = null;
  var vFitFailedEl = null;
  var controlPanel = null;

  var healthTimer = null;
  var _disconnected = false;

  // -----------------------------------------------------------------------
  // Initialise — grab overlay elements from the DOM
  // -----------------------------------------------------------------------
  function init() {
    disconnectedBanner = document.getElementById("disconnectedBanner");
    noCameraBanner = document.getElementById("noCameraBanner");
    hFitFailedEl = document.getElementById("hFitFailed");
    vFitFailedEl = document.getElementById("vFitFailed");
    controlPanel = document.getElementById("controlPanel");

    startHealthPoll();
  }

  // -----------------------------------------------------------------------
  // EPICS disconnected banner
  // -----------------------------------------------------------------------
  function showDisconnected() {
    if (_disconnected) return;
    _disconnected = true;
    if (disconnectedBanner) disconnectedBanner.style.display = "";
    if (controlPanel) controlPanel.classList.add("controls-disabled");
  }

  function hideDisconnected() {
    if (!_disconnected) return;
    _disconnected = false;
    if (disconnectedBanner) disconnectedBanner.style.display = "none";
    if (controlPanel) controlPanel.classList.remove("controls-disabled");
  }

  // -----------------------------------------------------------------------
  // Gaussian fit failure text in projection areas
  // -----------------------------------------------------------------------
  function showFitFailed(axis) {
    var el = axis === "y" ? vFitFailedEl : hFitFailedEl;
    if (el) el.style.display = "";
  }

  function hideFitFailed(axis) {
    var el = axis === "y" ? vFitFailedEl : hFitFailedEl;
    if (el) el.style.display = "none";
  }

  // -----------------------------------------------------------------------
  // No camera configured empty state
  // -----------------------------------------------------------------------
  function showNoCameraState() {
    if (noCameraBanner) noCameraBanner.style.display = "flex";
  }

  function hideNoCameraState() {
    if (noCameraBanner) noCameraBanner.style.display = "none";
  }

  // -----------------------------------------------------------------------
  // Health polling
  // -----------------------------------------------------------------------
  function startHealthPoll() {
    pollHealth(); // immediate first check
    healthTimer = setInterval(pollHealth, HEALTH_INTERVAL);
  }

  function pollHealth() {
    fetch(API_BASE + "/health")
      .then(function(r) { return r.json(); })
      .then(function(data) {
        if (data.status === "degraded" && !data.connected) {
          showDisconnected();
        } else {
          hideDisconnected();
        }
      })
      .catch(function() {
        // Fetch itself failed — server unreachable
        showDisconnected();
      });
  }

  // -----------------------------------------------------------------------
  // Check analysis payload for fit failures
  // -----------------------------------------------------------------------
  function checkAnalysis(msg) {
    var analysis = msg.analysis || {};

    // X fit
    var xFit = analysis.x_fit;
    if (xFit && !xFit.success) {
      showFitFailed("x");
    } else {
      hideFitFailed("x");
    }

    // Y fit
    var yFit = analysis.y_fit;
    if (yFit && !yFit.success) {
      showFitFailed("y");
    } else {
      hideFitFailed("y");
    }
  }

  return {
    init: init,
    showDisconnected: showDisconnected,
    hideDisconnected: hideDisconnected,
    showFitFailed: showFitFailed,
    hideFitFailed: hideFitFailed,
    showNoCameraState: showNoCameraState,
    hideNoCameraState: hideNoCameraState,
    checkAnalysis: checkAnalysis,
  };
})();
