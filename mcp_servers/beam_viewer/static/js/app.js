"use strict";

/**
 * Application entry point -- wires DOM elements to Connection + Renderer.
 */

(function() {
  // DOM refs
  var statusDot  = document.getElementById("statusDot");
  var statusText = document.getElementById("statusText");
  var frameNum   = document.getElementById("frameNum");
  var fpsVal     = document.getElementById("fpsVal");
  var noSignal   = document.getElementById("noSignal");
  var dimLabel   = document.getElementById("dimLabel");

  var currentCmap = "hot";
  var hasReceivedFrame = false;

  // -- Status indicator ---------------------------------------------------
  function updateStatus(state) {
    if (state === "connected") {
      statusDot.className = "status-dot connected";
      statusText.textContent = "Connected";
    } else if (state === "reconnecting") {
      statusDot.className = "status-dot reconnecting";
      statusText.textContent = "Reconnecting...";
    } else {
      statusDot.className = "status-dot disconnected";
      statusText.textContent = "Disconnected";
    }
  }

  // -- Colormap: synced from WS payload (msg.colormap) on each frame ------
  // Default to "hot" until the first frame arrives.

  // -- Theme ---------------------------------------------------------------
  ThemeManager.init();

  // -- Error states ---------------------------------------------------------
  ErrorStates.init();

  // -- Projection plots ----------------------------------------------------
  Projections.init();

  // -- Overlays (projection overlays, crosshair, drift) ---------------------
  if (typeof Overlays !== "undefined") {
    Overlays.init();
  }

  // -- Trending panel -------------------------------------------------------
  if (typeof Trending !== "undefined") {
    Trending.init();
  }

  // -- Splitters (drag-to-resize columns) -----------------------------------
  if (typeof Splitters !== "undefined") {
    Splitters.init();
  }

  // -- Frame handler ------------------------------------------------------
  Connection.onFrame(function(msg) {
    // Track colormap from WS readback (validated against renderer LUTs)
    if (msg.colormap && COLORMAPS[msg.colormap]) {
      currentCmap = msg.colormap;
    }

    if (msg.frame_jpeg_b64) {
      Renderer.renderFrame(msg.frame_jpeg_b64, currentCmap);
    }
    frameNum.textContent = msg.frame_number != null ? msg.frame_number : "--";
    fpsVal.textContent   = msg.fps != null ? msg.fps.toFixed(1) : "--";

    // Update projection plots with projection + analysis data
    Projections.update(msg);

    // Check for fit failures in analysis payload
    ErrorStates.checkAnalysis(msg);

    // Update ROI overlay and panel
    if (typeof BeamROI !== "undefined") {
      BeamROI.updateFromFrame(msg.roi);
    }

    // Update projection overlays, crosshair, and drift labels
    if (typeof Overlays !== "undefined") {
      Overlays.updateFromFrame(msg);
    }

    // Feed state readback to the control panel
    if (typeof ControlPanel !== "undefined" && ControlPanel.onWSMessage) {
      ControlPanel.onWSMessage(msg);
    }

    // Forward to trending panel (opportunistic — trending data may be in WS payload)
    if (typeof Trending !== "undefined" && Trending.onWSMessage) {
      Trending.onWSMessage(msg);
    }

    if (!hasReceivedFrame) {
      hasReceivedFrame = true;
      noSignal.style.display = "none";
    }
  });

  Connection.onStateChange(function(state) {
    updateStatus(state);
    // Show/hide disconnected banner based on WebSocket state
    if (state === "disconnected" || state === "reconnecting") {
      ErrorStates.showDisconnected();
    } else if (state === "connected") {
      ErrorStates.hideDisconnected();
    }
  });

  // -- Start --------------------------------------------------------------
  Connection.start();
})();
