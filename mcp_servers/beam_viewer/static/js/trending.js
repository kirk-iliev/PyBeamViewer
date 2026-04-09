"use strict";

/**
 * Trending panel -- 8 time-series charts (sigma, centroid, ROI sigma, drift)
 * rendered on canvas elements in a 4x2 grid below the main viewer.
 *
 * Fetches data from GET /trending/history and auto-refreshes.
 * Depth control sends POST /trending/depth.
 */

var Trending = (function() {

  // -----------------------------------------------------------------------
  // Configuration
  // -----------------------------------------------------------------------
  var POLL_INTERVAL_MS = 2000;
  var API_BASE = "..";

  var CHART_DEFS = [
    { key: "sigma_x",     label: "\u03C3_x",     color: "#89b4fa" },
    { key: "sigma_y",     label: "\u03C3_y",     color: "#a6e3a1" },
    { key: "centroid_x",  label: "Centroid X",   color: "#f9e2af" },
    { key: "centroid_y",  label: "Centroid Y",   color: "#cba6f7" },
    { key: "roi_sigma_x", label: "ROI \u03C3_x", color: "#f38ba8" },
    { key: "roi_sigma_y", label: "ROI \u03C3_y", color: "#fab387" },
    { key: "drift_x",     label: "Drift X",      color: "#74c7ec" },
    { key: "drift_y",     label: "Drift Y",      color: "#94e2d5" },
  ];

  // Plot style
  var COLORS = {
    bg:       "#1a1a2a",
    grid:     "rgba(255,255,255,0.08)",
    axis:     "#555",
    axisText: "#888",
    text:     "#cdd6f4",
    textDim:  "#888",
  };

  var PADDING = { top: 24, right: 10, bottom: 22, left: 50 };

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  var visible = false;
  var pollTimer = null;
  var canvases = [];   // array of {canvas, key, label, color}
  var lastHistory = null;
  var panelEl = null;
  var toggleBtn = null;
  var depthInput = null;

  // -----------------------------------------------------------------------
  // API helpers
  // -----------------------------------------------------------------------
  function fetchHistory() {
    return fetch(API_BASE + "/trending/history")
      .then(function(r) { return r.json(); });
  }

  function postDepth(depth) {
    return fetch(API_BASE + "/trending/depth", {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify({depth: depth}),
    });
  }

  function fetchConfig() {
    return fetch(API_BASE + "/trending")
      .then(function(r) { return r.json(); });
  }

  // -----------------------------------------------------------------------
  // Canvas chart renderer
  // -----------------------------------------------------------------------
  function drawChart(canvas, data, frameNumbers, opts) {
    var ctx = canvas.getContext("2d");
    var dpr = window.devicePixelRatio || 1;
    var cw = canvas.clientWidth;
    var ch = canvas.clientHeight;

    if (cw === 0 || ch === 0) return;

    if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
      canvas.width = cw * dpr;
      canvas.height = ch * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Clear
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, cw, ch);

    var pad = PADDING;
    var plotW = cw - pad.left - pad.right;
    var plotH = ch - pad.top - pad.bottom;
    if (plotW < 10 || plotH < 10) return;

    // Title
    ctx.fillStyle = COLORS.text;
    ctx.font = "bold 10px -apple-system, BlinkMacSystemFont, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(opts.label, pad.left, 4);

    if (!data || data.length === 0) {
      ctx.fillStyle = COLORS.textDim;
      ctx.font = "10px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("No data", cw / 2, ch / 2);
      return;
    }

    // Data range
    var n = data.length;
    var yMin = data[0];
    var yMax = data[0];
    for (var i = 1; i < n; i++) {
      if (data[i] < yMin) yMin = data[i];
      if (data[i] > yMax) yMax = data[i];
    }
    var yRange = yMax - yMin;
    if (yRange < 1e-9) yRange = 1;
    var yPad = yRange * 0.1;
    yMin -= yPad;
    yMax += yPad;
    yRange = yMax - yMin;

    function xMap(idx) { return pad.left + (idx / (n - 1 || 1)) * plotW; }
    function yMap(val) { return pad.top + plotH - ((val - yMin) / yRange) * plotH; }

    // Grid lines (3 horizontal)
    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    var nGrid = 3;
    for (var g = 0; g <= nGrid; g++) {
      var gy = pad.top + (g / nGrid) * plotH;
      ctx.moveTo(pad.left, gy);
      ctx.lineTo(pad.left + plotW, gy);
    }
    ctx.stroke();

    // Y-axis labels
    ctx.fillStyle = COLORS.axisText;
    ctx.font = "9px monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var g2 = 0; g2 <= nGrid; g2++) {
      var tickVal = yMax - (g2 / nGrid) * yRange;
      var tickY = pad.top + (g2 / nGrid) * plotH;
      var label;
      if (Math.abs(tickVal) >= 10000) {
        label = (tickVal / 1000).toFixed(1) + "k";
      } else if (Math.abs(tickVal) >= 1) {
        label = tickVal.toFixed(1);
      } else {
        label = tickVal.toFixed(3);
      }
      ctx.fillText(label, pad.left - 3, tickY);
    }

    // Axes
    ctx.strokeStyle = COLORS.axis;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top);
    ctx.lineTo(pad.left, pad.top + plotH);
    ctx.lineTo(pad.left + plotW, pad.top + plotH);
    ctx.stroke();

    // X-axis labels (frame numbers) — first and last
    if (frameNumbers && frameNumbers.length === n) {
      ctx.fillStyle = COLORS.axisText;
      ctx.font = "9px monospace";
      ctx.textBaseline = "top";
      var xLabelY = pad.top + plotH + 4;

      ctx.textAlign = "left";
      ctx.fillText(Math.round(frameNumbers[0]).toString(), pad.left, xLabelY);

      ctx.textAlign = "right";
      ctx.fillText(Math.round(frameNumbers[n - 1]).toString(), pad.left + plotW, xLabelY);
    }

    // Data line
    ctx.strokeStyle = opts.color;
    ctx.lineWidth = 1.4;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(xMap(0), yMap(data[0]));
    for (var j = 1; j < n; j++) {
      ctx.lineTo(xMap(j), yMap(data[j]));
    }
    ctx.stroke();

    // Current value label (top right)
    var lastVal = data[n - 1];
    var valStr;
    if (Math.abs(lastVal) >= 1000) {
      valStr = (lastVal / 1000).toFixed(2) + "k";
    } else if (Math.abs(lastVal) >= 1) {
      valStr = lastVal.toFixed(2);
    } else {
      valStr = lastVal.toFixed(4);
    }
    ctx.fillStyle = opts.color;
    ctx.font = "bold 10px monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "top";
    ctx.fillText(valStr, cw - pad.right, 4);
  }

  // -----------------------------------------------------------------------
  // Build DOM
  // -----------------------------------------------------------------------
  function buildPanel() {
    panelEl = document.getElementById("trendingPanel");
    if (!panelEl) return;

    // Toggle button in toolbar
    toggleBtn = document.getElementById("trendingToggle");
    if (toggleBtn) {
      toggleBtn.addEventListener("click", function() {
        toggle();
      });
    }

    // Depth control
    depthInput = document.getElementById("trendingDepth");
    if (depthInput) {
      depthInput.addEventListener("change", function() {
        var val = parseInt(depthInput.value, 10);
        if (isNaN(val) || val < 50) val = 50;
        if (val > 2000) val = 2000;
        depthInput.value = val;
        postDepth(val).catch(function() {});
      });
    }

    // Create chart canvases in the grid
    var grid = document.getElementById("trendingGrid");
    if (!grid) return;

    canvases = [];
    for (var i = 0; i < CHART_DEFS.length; i++) {
      var def = CHART_DEFS[i];
      var cell = document.createElement("div");
      cell.className = "trending-cell";
      var canvas = document.createElement("canvas");
      canvas.className = "trending-canvas";
      cell.appendChild(canvas);
      grid.appendChild(cell);
      canvases.push({
        canvas: canvas,
        key: def.key,
        label: def.label,
        color: def.color,
      });
    }

    // Load initial config
    fetchConfig().then(function(cfg) {
      if (depthInput && cfg.depth) {
        depthInput.value = cfg.depth;
      }
    }).catch(function() {});
  }

  // -----------------------------------------------------------------------
  // Toggle visibility
  // -----------------------------------------------------------------------
  function toggle() {
    visible = !visible;
    if (panelEl) {
      panelEl.style.display = visible ? "" : "none";
    }
    if (toggleBtn) {
      toggleBtn.classList.toggle("active", visible);
    }
    if (visible) {
      refresh();
      startPolling();
    } else {
      stopPolling();
    }
  }

  // -----------------------------------------------------------------------
  // Polling
  // -----------------------------------------------------------------------
  function startPolling() {
    stopPolling();
    pollTimer = setInterval(refresh, POLL_INTERVAL_MS);
  }

  function stopPolling() {
    if (pollTimer) {
      clearInterval(pollTimer);
      pollTimer = null;
    }
  }

  function refresh() {
    fetchHistory().then(function(history) {
      lastHistory = history;
      renderAll();
    }).catch(function() {});
  }

  // -----------------------------------------------------------------------
  // Render all charts
  // -----------------------------------------------------------------------
  function renderAll() {
    if (!lastHistory || lastHistory.count === 0) return;
    for (var i = 0; i < canvases.length; i++) {
      var c = canvases[i];
      var data = lastHistory[c.key] || [];
      drawChart(c.canvas, data, lastHistory.frame_number || [], {
        label: c.label,
        color: c.color,
      });
    }
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------
  function init() {
    buildPanel();
    // Start hidden
    if (panelEl) panelEl.style.display = "none";
  }

  /**
   * Called from the main WS message handler — if trending data
   * is included in the frame payload, update immediately.
   */
  function onWSMessage(msg) {
    if (msg.trending && visible) {
      lastHistory = msg.trending;
      renderAll();
    }
  }

  return {
    init: init,
    toggle: toggle,
    refresh: refresh,
    onWSMessage: onWSMessage,
  };

})();
