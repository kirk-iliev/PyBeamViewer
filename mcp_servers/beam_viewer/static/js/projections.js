"use strict";

/**
 * H/V projection plot components -- draws projection line charts with
 * optional Gaussian fit overlays on dedicated canvas elements.
 *
 * Layout mirrors the Qt ProjectionPlot widget: horizontal projection
 * below the image, vertical projection to the right.
 */

var Projections = (function() {

  // -----------------------------------------------------------------------
  // Style constants (match dark theme from index.html)
  // -----------------------------------------------------------------------
  // Colors match gui/theme.py DARK. CSS vars used where possible.
  var COLORS = {
    bg:        "#1a1a2e",
    grid:      "rgba(255,255,255,0.08)",
    axis:      "#555",
    axisText:  "#888",
    hCurve:    "#00e5ff",   // theme.h_curve (dark) — cyan
    vCurve:    "#ce93d8",   // theme.v_curve (dark) — lavender
    fitCurve:  "#ff5555",   // theme.fit_curve (dark) — red dashed
    roiCurve:  "rgba(243,139,168,0.7)",
    textDim:   "#7a7a9a",
    text:      "#e0e0e0",
  };

  var PADDING = { top: 28, right: 12, bottom: 28, left: 50 };
  var FIT_DASH = [6, 4];

  // -----------------------------------------------------------------------
  // Helper: Gaussian function  A * exp(-(x - mu)^2 / (2 * sigma^2)) + offset
  // -----------------------------------------------------------------------
  function gaussian(x, amplitude, centroid, sigma, offset) {
    var dx = x - centroid;
    return amplitude * Math.exp(-(dx * dx) / (2 * sigma * sigma)) + (offset || 0);
  }

  // -----------------------------------------------------------------------
  // Generic plot renderer
  // -----------------------------------------------------------------------
  function drawPlot(canvas, projection, fitParams, opts) {
    var ctx = canvas.getContext("2d");
    var dpr = window.devicePixelRatio || 1;
    var cw  = canvas.clientWidth;
    var ch  = canvas.clientHeight;

    // Resize backing store to match CSS size at device resolution
    if (canvas.width !== cw * dpr || canvas.height !== ch * dpr) {
      canvas.width  = cw * dpr;
      canvas.height = ch * dpr;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // Clear
    ctx.fillStyle = COLORS.bg;
    ctx.fillRect(0, 0, cw, ch);

    if (!projection || projection.length === 0) return;

    var pad = PADDING;
    var plotW = cw - pad.left - pad.right;
    var plotH = ch - pad.top  - pad.bottom;
    if (plotW < 10 || plotH < 10) return;

    // Data range
    var n   = projection.length;
    var yMin = projection[0];
    var yMax = projection[0];
    for (var i = 1; i < n; i++) {
      if (projection[i] < yMin) yMin = projection[i];
      if (projection[i] > yMax) yMax = projection[i];
    }

    // Include fit peak in y-range if present
    if (fitParams && fitParams.success) {
      var fitPeak = (fitParams.amplitude || 0) + (fitParams.offset || 0);
      if (fitPeak > yMax) yMax = fitPeak;
      var fitBase = fitParams.offset || 0;
      if (fitBase < yMin) yMin = fitBase;
    }

    var yRange = yMax - yMin;
    if (yRange < 1e-6) yRange = 1;
    var yPad = yRange * 0.08;
    yMin -= yPad;
    yMax += yPad;
    yRange = yMax - yMin;

    // Map functions
    function xMap(idx) { return pad.left + (idx / (n - 1 || 1)) * plotW; }
    function yMap(val) { return pad.top + plotH - ((val - yMin) / yRange) * plotH; }

    // Grid lines — 4 horizontal
    ctx.strokeStyle = COLORS.grid;
    ctx.lineWidth = 1;
    ctx.beginPath();
    var nGrid = 4;
    for (var g = 0; g <= nGrid; g++) {
      var gy = pad.top + (g / nGrid) * plotH;
      ctx.moveTo(pad.left, gy);
      ctx.lineTo(pad.left + plotW, gy);
    }
    ctx.stroke();

    // Y-axis tick labels
    ctx.fillStyle = COLORS.axisText;
    ctx.font = "10px monospace";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    for (var g2 = 0; g2 <= nGrid; g2++) {
      var tickVal = yMax - (g2 / nGrid) * yRange;
      var tickY   = pad.top + (g2 / nGrid) * plotH;
      var label   = tickVal >= 1000 ? (tickVal / 1000).toFixed(1) + "k"
                  : tickVal >= 1    ? tickVal.toFixed(0)
                  :                   tickVal.toFixed(2);
      ctx.fillText(label, pad.left - 4, tickY);
    }

    // Axis lines
    ctx.strokeStyle = COLORS.axis;
    ctx.lineWidth = 1;
    ctx.beginPath();
    ctx.moveTo(pad.left, pad.top);
    ctx.lineTo(pad.left, pad.top + plotH);
    ctx.lineTo(pad.left + plotW, pad.top + plotH);
    ctx.stroke();

    // --- Draw projection curve ---
    var curveColor = opts.curveColor || COLORS.hCurve;
    ctx.strokeStyle = curveColor;
    ctx.lineWidth = 1.4;
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.moveTo(xMap(0), yMap(projection[0]));
    for (var j = 1; j < n; j++) {
      ctx.lineTo(xMap(j), yMap(projection[j]));
    }
    ctx.stroke();

    // --- Draw Gaussian fit overlay ---
    if (fitParams && fitParams.success &&
        fitParams.sigma != null && fitParams.centroid != null && fitParams.amplitude != null) {
      ctx.strokeStyle = COLORS.fitCurve;
      ctx.lineWidth = 1.6;
      ctx.setLineDash(FIT_DASH);
      ctx.beginPath();
      var started = false;
      for (var k = 0; k < n; k++) {
        var fitY = gaussian(k, fitParams.amplitude, fitParams.centroid, fitParams.sigma, fitParams.offset);
        var px = xMap(k);
        var py = yMap(fitY);
        if (!started) { ctx.moveTo(px, py); started = true; }
        else          { ctx.lineTo(px, py); }
      }
      ctx.stroke();
      ctx.setLineDash([]);
    }

    // --- Title label ---
    ctx.fillStyle = COLORS.text;
    ctx.font = "bold 11px -apple-system, BlinkMacSystemFont, monospace";
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(opts.title || "", pad.left, 4);

    // --- Stats text ---
    if (fitParams && fitParams.success &&
        fitParams.sigma != null && fitParams.centroid != null && fitParams.amplitude != null) {
      var sigmaText;
      if (fitParams.sigma_um != null) {
        sigmaText = "\u03C3: " + fitParams.sigma_um.toFixed(2) + " " + (fitParams.unit_label || "um") +
                    " (" + fitParams.sigma.toFixed(1) + " px)";
      } else {
        sigmaText = "\u03C3: " + fitParams.sigma.toFixed(2) + " px";
      }
      var statsStr = sigmaText +
        "    Cen: " + fitParams.centroid.toFixed(1) + " px" +
        "    Amp: " + fitParams.amplitude.toFixed(0);

      ctx.fillStyle = COLORS.text;
      ctx.font = "10px monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillText(statsStr, cw - pad.right, 4);
    } else {
      ctx.fillStyle = COLORS.textDim;
      ctx.font = "10px monospace";
      ctx.textAlign = "right";
      ctx.textBaseline = "top";
      ctx.fillText("\u03C3: \u2014\u2014    Cen: \u2014\u2014    Amp: \u2014\u2014", cw - pad.right, 4);
    }
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  var hCanvas = null;
  var vCanvas = null;
  var roiHCanvas = null;
  var roiVCanvas = null;

  // Last-drawn data — used to re-render on window resize
  var _lastHProj = null,   _lastHFit = null;
  var _lastVProj = null,   _lastVFit = null;
  var _lastROIHProj = null, _lastROIHFit = null;
  var _lastROIVProj = null, _lastROIVFit = null;

  function init() {
    hCanvas = document.getElementById("hProjCanvas");
    vCanvas = document.getElementById("vProjCanvas");
    roiHCanvas = document.getElementById("roiHProjCanvas");
    roiVCanvas = document.getElementById("roiVProjCanvas");
  }

  /**
   * Update both full-image projection plots from a WebSocket frame message.
   *
   * @param {Object} msg  - Full WebSocket frame payload containing
   *   msg.projections.x_projection, msg.projections.y_projection,
   *   msg.analysis.x_fit, msg.analysis.y_fit
   */
  function update(msg) {
    if (!hCanvas || !vCanvas) return;

    var proj = msg.projections || {};
    var analysis = msg.analysis || {};

    _lastHProj = proj.x_projection || null;
    _lastHFit  = analysis.x_fit    || null;
    _lastVProj = proj.y_projection || null;
    _lastVFit  = analysis.y_fit    || null;

    drawPlot(hCanvas, _lastHProj, _lastHFit, {
      title: "Horizontal Projection  (Full Image)",
      curveColor: COLORS.hCurve,
    });

    drawPlot(vCanvas, _lastVProj, _lastVFit, {
      title: "Vertical Projection  (Full Image)",
      curveColor: COLORS.vCurve,
    });
  }

  /**
   * Update ROI projection plots (called from roi.js with REST data).
   *
   * @param {Object} projections  - { x_projection: [...], y_projection: [...] }
   * @param {Object} [fit]        - { roi_x_fit: {...}, roi_y_fit: {...} }
   */
  function updateROI(projections, fit) {
    if (!roiHCanvas || !roiVCanvas) return;
    if (!projections) return;

    var xFit = fit && fit.roi_x_fit ? fit.roi_x_fit : null;
    var yFit = fit && fit.roi_y_fit ? fit.roi_y_fit : null;

    _lastROIHProj = projections.x_projection || null;
    _lastROIHFit  = xFit;
    _lastROIVProj = projections.y_projection || null;
    _lastROIVFit  = yFit;

    drawPlot(roiHCanvas, _lastROIHProj, xFit, {
      title: "Horizontal Projection  (ROI)",
      curveColor: COLORS.hCurve,
    });

    drawPlot(roiVCanvas, _lastROIVProj, yFit, {
      title: "Vertical Projection  (ROI)",
      curveColor: COLORS.vCurve,
    });
  }

  /** Re-render all plots with the last known data (called on window resize). */
  function redrawAll() {
    if (hCanvas && _lastHProj) {
      drawPlot(hCanvas, _lastHProj, _lastHFit, {
        title: "Horizontal Projection  (Full Image)",
        curveColor: COLORS.hCurve,
      });
    }
    if (vCanvas && _lastVProj) {
      drawPlot(vCanvas, _lastVProj, _lastVFit, {
        title: "Vertical Projection  (Full Image)",
        curveColor: COLORS.vCurve,
      });
    }
    if (roiHCanvas && _lastROIHProj) {
      drawPlot(roiHCanvas, _lastROIHProj, _lastROIHFit, {
        title: "Horizontal Projection  (ROI)",
        curveColor: COLORS.hCurve,
      });
    }
    if (roiVCanvas && _lastROIVProj) {
      drawPlot(roiVCanvas, _lastROIVProj, _lastROIVFit, {
        title: "Vertical Projection  (ROI)",
        curveColor: COLORS.vCurve,
      });
    }
  }

  // Re-render on window resize so plots stay crisp at any window size
  var _resizeTimer = null;
  window.addEventListener("resize", function() {
    clearTimeout(_resizeTimer);
    _resizeTimer = setTimeout(redrawAll, 60);
  });

  return { init: init, update: update, updateROI: updateROI, redrawAll: redrawAll };
})();
