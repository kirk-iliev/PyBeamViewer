"use strict";

/**
 * Trending panel -- 3 dual-trace sub-plots matching PyQt's TrendingPanel:
 *   1. Full Image Beam Size (σx + σy)
 *   2. ROI Beam Size (σx + σy)
 *   3. Centroid Drift (Δx + Δy)
 *
 * Each sub-plot draws two traces with a title and stats legend.
 * Fetches data from GET /trending/history and auto-refreshes.
 * Depth control sends POST /trending/depth.
 */

var Trending = (function() {

  // -----------------------------------------------------------------------
  // Configuration
  // -----------------------------------------------------------------------
  var POLL_INTERVAL_MS = 2000;
  var API_BASE = "..";

  // 3 sub-plots matching PyQt's _TrendSubPlot instances.
  // colorA/colorB starting with "--" are resolved as CSS custom properties
  // at draw time so they follow the active theme automatically.
  // 2 sub-plots matching PyQt TrendingPanel when Fit ROI is active:
  //   1. ROI Beam Size — σx and σy from the ROI Gaussian fit
  //   2. Centroid      — centroid x and y position vs. frame number
  // Both are shown/hidden together when fit_roi_enabled toggles.
  var SUBPLOT_DEFS = [
    {
      title: "ROI Beam Size",
      keyA: "roi_sigma_x",  keyB: "roi_sigma_y",
      labelA: "\u03C3x",    labelB: "\u03C3y",
      colorA: "--h-curve",   colorB: "--v-curve",
    },
    {
      title: "Centroid Drift",
      keyA: "centroid_x",   keyB: "centroid_y",
      labelA: "x",           labelB: "y",
      colorA: "#2ecc71",     colorB: "#e67e22",  // green + orange
    },
  ];

  // Style helpers — read CSS custom properties at draw time so theme
  // switches (dark ↔ light) are reflected without a page reload.
  function getColors() {
    var st = getComputedStyle(document.documentElement);
    function v(n) { return st.getPropertyValue(n).trim(); }
    return {
      bg:       v("--plot-bg"),
      grid:     v("--plot-grid"),
      axis:     v("--plot-axis"),
      axisText: v("--text-dim"),
      text:     v("--text"),
      textDim:  v("--text-dim"),
    };
  }

  function resolveColor(colorOrVar) {
    if (colorOrVar && colorOrVar.charAt(0) === "-") {
      return getComputedStyle(document.documentElement).getPropertyValue(colorOrVar).trim();
    }
    return colorOrVar;
  }

  var PADDING = { top: 28, right: 10, bottom: 22, left: 50 };

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  var visible = false;
  var pollTimer = null;
  var subplots = [];  // array of {canvas, cell, def, active}
  var lastHistory = null;
  var panelEl = null;
  var toggleBtn = null;
  var depthInput = null;
  var placeholderEl = null;

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
  // Canvas chart renderer — dual-trace version
  // -----------------------------------------------------------------------
  function drawDualChart(canvas, dataA, dataB, frameNumbers, opts) {
    var COLORS = getColors();
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
    ctx.font = "bold 11px -apple-system, BlinkMacSystemFont, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(opts.title || "", pad.left, 4);

    // Filter out leading nulls; treat an all-null array as empty
    var hasA = dataA && dataA.some(function(v) { return v != null; });
    var hasB = dataB && dataB.some(function(v) { return v != null; });

    if (!hasA && !hasB) {
      ctx.fillStyle = COLORS.textDim;
      ctx.font = "10px monospace";
      ctx.textAlign = "center";
      ctx.textBaseline = "middle";
      ctx.fillText("No data", cw / 2, ch / 2);
      return;
    }

    // Compute combined data range from both traces (skip nulls)
    var n = Math.max(hasA ? dataA.length : 0, hasB ? dataB.length : 0);
    var yMin = Infinity;
    var yMax = -Infinity;

    if (hasA) {
      for (var i = 0; i < dataA.length; i++) {
        if (dataA[i] != null && dataA[i] < yMin) yMin = dataA[i];
        if (dataA[i] != null && dataA[i] > yMax) yMax = dataA[i];
      }
    }
    if (hasB) {
      for (var i = 0; i < dataB.length; i++) {
        if (dataB[i] != null && dataB[i] < yMin) yMin = dataB[i];
        if (dataB[i] != null && dataB[i] > yMax) yMax = dataB[i];
      }
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

    // Clip traces to the plot area so spikes are cut at axis limits
    ctx.save();
    ctx.beginPath();
    ctx.rect(pad.left, pad.top, plotW, plotH);
    ctx.clip();

    if (hasA) {
      drawTrace(ctx, dataA, n, xMap, yMap, resolveColor(opts.colorA));
    }
    if (hasB) {
      drawTrace(ctx, dataB, n, xMap, yMap, resolveColor(opts.colorB));
    }

    ctx.restore();

    // Stats legend (top right, matching PyQt: "labelA: val  labelB: val")
    var statsStr = "";
    if (hasA) {
      var lastA = lastNonNull(dataA);
      statsStr += opts.labelA + ": " + (lastA != null ? formatVal(lastA) : "\u2014\u2014");
    } else {
      statsStr += opts.labelA + ": \u2014\u2014";
    }
    statsStr += "    ";
    if (hasB) {
      var lastB = lastNonNull(dataB);
      statsStr += opts.labelB + ": " + (lastB != null ? formatVal(lastB) : "\u2014\u2014");
    } else {
      statsStr += opts.labelB + ": \u2014\u2014";
    }
    ctx.fillStyle = COLORS.text;
    ctx.font = "10px monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "top";
    ctx.fillText(statsStr, cw - pad.right, 4);
  }

  function drawTrace(ctx, data, n, xMap, yMap, color) {
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.3;
    ctx.setLineDash([]);
    ctx.beginPath();
    var penDown = false;
    for (var j = 0; j < data.length; j++) {
      if (data[j] == null) { penDown = false; continue; }
      if (!penDown) { ctx.moveTo(xMap(j), yMap(data[j])); penDown = true; }
      else          { ctx.lineTo(xMap(j), yMap(data[j])); }
    }
    ctx.stroke();
  }

  function lastNonNull(arr) {
    for (var i = arr.length - 1; i >= 0; i--) {
      if (arr[i] != null) return arr[i];
    }
    return null;
  }

  function formatVal(v) {
    if (Math.abs(v) >= 1000) return (v / 1000).toFixed(2) + "k";
    if (Math.abs(v) >= 1)    return v.toFixed(3);
    return v.toFixed(4);
  }

  // -----------------------------------------------------------------------
  // Build DOM
  // -----------------------------------------------------------------------
  function buildPanel() {
    panelEl = document.getElementById("trendingPanel");
    if (!panelEl) return;

    // Depth control (in trending toolbar)
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

    // Create 3 sub-plot canvases (stacked vertically, hidden until active)
    var stack = document.getElementById("trendingGrid");
    if (!stack) return;

    subplots = [];
    for (var i = 0; i < SUBPLOT_DEFS.length; i++) {
      var def = SUBPLOT_DEFS[i];
      var cell = document.createElement("div");
      cell.className = "trending-cell";
      cell.style.display = "none";  // hidden until enabled via WS state
      var canvas = document.createElement("canvas");
      canvas.className = "trending-canvas";
      cell.appendChild(canvas);
      stack.appendChild(cell);
      subplots.push({ canvas: canvas, cell: cell, def: def, active: false });
    }

    // Placeholder shown when trending is open but no sub-plots are active
    placeholderEl = document.createElement("div");
    placeholderEl.style.cssText = "flex:1;display:flex;align-items:center;" +
      "justify-content:center;color:var(--text-dim);font-size:12px;";
    placeholderEl.textContent = "Enable Fit ROI or Fit Full Image to show trends";
    stack.appendChild(placeholderEl);

    // Load initial config
    fetchConfig().then(function(cfg) {
      if (depthInput && cfg.depth) {
        depthInput.value = cfg.depth;
      }
    }).catch(function() {});
  }

  // -----------------------------------------------------------------------
  // Toggle visibility (called from control panel trending button)
  // -----------------------------------------------------------------------
  function toggle() {
    visible = !visible;
    if (panelEl) {
      panelEl.style.display = visible ? "" : "none";
    }
    if (visible) {
      refresh();
      startPolling();
    } else {
      stopPolling();
    }
  }

  function setVisible(v) {
    if (v === visible) return;
    toggle();
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
  // Sub-plot visibility (driven by WS analysis/drift state, like PyQt)
  // -----------------------------------------------------------------------
  function setSubplotActive(idx, active) {
    if (idx < 0 || idx >= subplots.length) return;
    var sp = subplots[idx];
    if (sp.active === active) return;
    sp.active = active;
    sp.cell.style.display = active ? "" : "none";
    // Update placeholder
    if (placeholderEl) {
      var anyActive = false;
      for (var i = 0; i < subplots.length; i++) {
        if (subplots[i].active) { anyActive = true; break; }
      }
      placeholderEl.style.display = anyActive ? "none" : "";
    }
    // Render immediately if we just became active and have data
    if (active && lastHistory && lastHistory.count > 0) {
      renderSubplot(idx);
    }
  }

  function renderSubplot(idx) {
    var sp = subplots[idx];
    var fn = (lastHistory && lastHistory.frame_number) || [];
    var def = sp.def;
    drawDualChart(sp.canvas, lastHistory[def.keyA] || [], lastHistory[def.keyB] || [], fn, {
      title: def.title,
      labelA: def.labelA,
      labelB: def.labelB,
      colorA: def.colorA,
      colorB: def.colorB,
    });
  }

  // -----------------------------------------------------------------------
  // Render all active sub-plots
  // -----------------------------------------------------------------------
  function renderAll() {
    if (!lastHistory || lastHistory.count === 0) return;
    for (var i = 0; i < subplots.length; i++) {
      if (!subplots[i].active) continue;
      renderSubplot(i);
    }
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------
  function init() {
    buildPanel();
    // Start hidden
    if (panelEl) panelEl.style.display = "none";

    // Re-render on window resize so charts stay crisp at any window size
    var _resizeTimer = null;
    window.addEventListener("resize", function() {
      if (!visible) return;
      clearTimeout(_resizeTimer);
      _resizeTimer = setTimeout(renderAll, 60);
    });

    // Re-render immediately when theme switches so backgrounds update
    window.addEventListener("themechange", function() {
      if (visible) renderAll();
    });
  }

  /**
   * Called from the main WS message handler on every frame.
   * Updates sub-plot visibility to match PyQt's conditional display logic:
   *   subplot[0] Full Image Beam Size → when fit_full_enabled
   *   subplot[1] ROI Beam Size        → when fit_roi_enabled
   *   subplot[2] Centroid Drift       → when a centroid reference is set
   */
  function onWSMessage(msg) {
    if (msg.analysis) {
      var roiActive = !!msg.analysis.fit_roi_enabled;
      setSubplotActive(0, roiActive);  // ROI Beam Size
      setSubplotActive(1, roiActive);  // Centroid position
    }

    if (msg.trending && visible) {
      lastHistory = msg.trending;
      renderAll();
    }
  }

  return {
    init: init,
    toggle: toggle,
    setVisible: setVisible,
    refresh: refresh,
    onWSMessage: onWSMessage,
  };

})();
