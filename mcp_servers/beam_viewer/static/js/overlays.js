"use strict";

/**
 * overlays.js — Projection overlays on the image canvas, crosshair at
 * centroid reference, and drift labels (Δx / Δy in px and µm).
 *
 * Draws directly on a transparent overlay canvas that sits on top of the
 * beam image.  Controls are added to the control-panel sidebar.
 *
 * Public API (attached to window.Overlays):
 *   - init()                — build DOM, fetch initial state
 *   - updateFromFrame(msg)  — called each WS frame
 */

var Overlays = (function() {

  var API_BASE = "..";

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  var settings = {
    h_enabled: false,
    h_side: "bottom",
    v_enabled: false,
    v_side: "right",
    scale: 0.20,
    show_full: true,
    show_roi: false,
  };

  var crosshairEnabled = false;
  var calibration = null; // {is_calibrated, um_per_pixel, unit_label}
  var lastMsg = null;     // most recent WS frame message

  // -----------------------------------------------------------------------
  // DOM references
  // -----------------------------------------------------------------------
  var canvas = document.getElementById("beamCanvas");
  var canvasArea = canvas.closest(".canvas-area");
  var panel = document.getElementById("controlPanel");

  // Overlay canvas for drawing on top of beam image
  var overlay = document.createElement("canvas");
  overlay.id = "overlaysCanvas";
  overlay.style.cssText =
    "position:absolute;top:0;left:0;width:100%;height:100%;" +
    "pointer-events:none;image-rendering:pixelated;z-index:5;";
  canvasArea.appendChild(overlay);
  var ctx = overlay.getContext("2d");

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  function postJSON(path, body) {
    return fetch(API_BASE + path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
  }

  function syncOverlaySize() {
    if (overlay.width !== canvas.width || overlay.height !== canvas.height) {
      overlay.width = canvas.width;
      overlay.height = canvas.height;
    }
  }

  // -----------------------------------------------------------------------
  // Build control panel section
  // -----------------------------------------------------------------------
  var hToggle, vToggle, hSideSelect, vSideSelect, scaleSlider, scaleLabel;
  var showFullBtn, showRoiBtn, crosshairToggle;
  var driftLabel;

  function buildControls() {
    var section = el("div", "cp-section");

    var header = el("div", "cp-section-header");
    var chevron = el("span", "cp-chevron", "\u25BE");
    header.appendChild(chevron);
    header.appendChild(document.createTextNode(" Overlays"));
    header.addEventListener("click", function() {
      if (body.style.display === "none") {
        body.style.display = "";
        chevron.textContent = "\u25BE";
      } else {
        body.style.display = "none";
        chevron.textContent = "\u25B8";
      }
    });
    section.appendChild(header);

    var body = el("div", "cp-section-body");

    // -- Projection overlay toggles --
    var projRow = el("div", "cp-btn-row");
    hToggle = el("button", "cp-btn cp-toggle", "H Overlay");
    vToggle = el("button", "cp-btn cp-toggle", "V Overlay");
    projRow.appendChild(hToggle);
    projRow.appendChild(vToggle);
    body.appendChild(projRow);

    // -- Side selectors --
    var sideRow = el("div", "cp-row");
    var hLabel = el("label", "cp-label", "H side:");
    hSideSelect = document.createElement("select");
    hSideSelect.className = "cp-select";
    var hOpts = ["bottom", "top"];
    hOpts.forEach(function(v) {
      var o = document.createElement("option");
      o.value = v; o.textContent = v;
      hSideSelect.appendChild(o);
    });
    sideRow.appendChild(hLabel);
    sideRow.appendChild(hSideSelect);
    body.appendChild(sideRow);

    var sideRow2 = el("div", "cp-row");
    var vLabel = el("label", "cp-label", "V side:");
    vSideSelect = document.createElement("select");
    vSideSelect.className = "cp-select";
    var vOpts = ["right", "left"];
    vOpts.forEach(function(v) {
      var o = document.createElement("option");
      o.value = v; o.textContent = v;
      vSideSelect.appendChild(o);
    });
    sideRow2.appendChild(vLabel);
    sideRow2.appendChild(vSideSelect);
    body.appendChild(sideRow2);

    // -- Scale slider --
    var scaleRow = el("div", "cp-row");
    var sLabel = el("label", "cp-label", "Scale:");
    scaleSlider = document.createElement("input");
    scaleSlider.type = "range";
    scaleSlider.min = "0.05";
    scaleSlider.max = "0.50";
    scaleSlider.step = "0.01";
    scaleSlider.value = String(settings.scale);
    scaleSlider.style.flex = "1";
    scaleLabel = el("span", "", (settings.scale * 100).toFixed(0) + "%");
    scaleLabel.style.cssText = "width:34px;text-align:right;font-size:11px;color:var(--text-dim);";
    scaleRow.appendChild(sLabel);
    scaleRow.appendChild(scaleSlider);
    scaleRow.appendChild(scaleLabel);
    body.appendChild(scaleRow);

    // -- Show full / ROI toggle --
    var modeRow = el("div", "cp-btn-row");
    showFullBtn = el("button", "cp-btn cp-toggle", "Full");
    showRoiBtn = el("button", "cp-btn cp-toggle", "ROI");
    modeRow.appendChild(showFullBtn);
    modeRow.appendChild(showRoiBtn);
    body.appendChild(modeRow);

    // -- Crosshair toggle --
    crosshairToggle = el("button", "cp-btn cp-toggle", "Crosshair");
    crosshairToggle.style.width = "100%";
    crosshairToggle.style.marginBottom = "6px";
    body.appendChild(crosshairToggle);

    // -- Drift label --
    driftLabel = el("div", "cp-status-text", "\u0394x: --  \u0394y: --");
    body.appendChild(driftLabel);

    section.appendChild(body);
    panel.appendChild(section);

    // -- Event handlers --
    hToggle.addEventListener("click", function() {
      settings.h_enabled = !settings.h_enabled;
      hToggle.classList.toggle("active", settings.h_enabled);
      pushSettings({h_enabled: settings.h_enabled});
      redraw();
    });

    vToggle.addEventListener("click", function() {
      settings.v_enabled = !settings.v_enabled;
      vToggle.classList.toggle("active", settings.v_enabled);
      pushSettings({v_enabled: settings.v_enabled});
      redraw();
    });

    hSideSelect.addEventListener("change", function() {
      settings.h_side = hSideSelect.value;
      pushSettings({h_side: settings.h_side});
      redraw();
    });

    vSideSelect.addEventListener("change", function() {
      settings.v_side = vSideSelect.value;
      pushSettings({v_side: settings.v_side});
      redraw();
    });

    scaleSlider.addEventListener("input", function() {
      settings.scale = parseFloat(scaleSlider.value);
      scaleLabel.textContent = (settings.scale * 100).toFixed(0) + "%";
      redraw();
    });

    scaleSlider.addEventListener("change", function() {
      settings.scale = parseFloat(scaleSlider.value);
      pushSettings({scale: settings.scale});
    });

    showFullBtn.addEventListener("click", function() {
      settings.show_full = !settings.show_full;
      showFullBtn.classList.toggle("active", settings.show_full);
      pushSettings({show_full: settings.show_full});
      redraw();
    });

    showRoiBtn.addEventListener("click", function() {
      settings.show_roi = !settings.show_roi;
      showRoiBtn.classList.toggle("active", settings.show_roi);
      pushSettings({show_roi: settings.show_roi});
      redraw();
    });

    crosshairToggle.addEventListener("click", function() {
      crosshairEnabled = !crosshairEnabled;
      crosshairToggle.classList.toggle("active", crosshairEnabled);
      postJSON("/centroid/crosshair", {enabled: crosshairEnabled}).catch(function() {});
      redraw();
    });
  }

  function pushSettings(partial) {
    postJSON("/overlays", partial).catch(function() {});
  }

  function syncControlsFromSettings() {
    hToggle.classList.toggle("active", settings.h_enabled);
    vToggle.classList.toggle("active", settings.v_enabled);
    hSideSelect.value = settings.h_side;
    vSideSelect.value = settings.v_side;
    scaleSlider.value = String(settings.scale);
    scaleLabel.textContent = (settings.scale * 100).toFixed(0) + "%";
    showFullBtn.classList.toggle("active", settings.show_full);
    showRoiBtn.classList.toggle("active", settings.show_roi);
    crosshairToggle.classList.toggle("active", crosshairEnabled);
  }

  // -----------------------------------------------------------------------
  // Drawing
  // -----------------------------------------------------------------------

  function redraw() {
    syncOverlaySize();
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    if (lastMsg) {
      drawProjectionOverlays(lastMsg);
      drawCrosshair(lastMsg);
      updateDriftLabel(lastMsg);
    }
  }

  // -- Projection overlays on the image --
  function drawProjectionOverlays(msg) {
    var proj = msg.projections;
    if (!proj) return;

    var imgW = canvas.width;
    var imgH = canvas.height;

    if (settings.h_enabled && settings.show_full && proj.x_projection) {
      drawHProjection(proj.x_projection, imgW, imgH, "rgba(0,229,255,0.55)");
    }
    if (settings.v_enabled && settings.show_full && proj.y_projection) {
      drawVProjection(proj.y_projection, imgW, imgH, "rgba(206,147,216,0.55)");
    }

    // ROI projections (if available in msg.roi)
    if (settings.show_roi && msg.roi && msg.roi.active) {
      var roiR = msg.roi.roi;
      if (settings.h_enabled && msg.roi.x_projection) {
        drawHProjectionROI(msg.roi.x_projection, roiR, imgW, imgH, "rgba(243,139,168,0.55)");
      }
      if (settings.v_enabled && msg.roi.y_projection) {
        drawVProjectionROI(msg.roi.y_projection, roiR, imgW, imgH, "rgba(243,139,168,0.55)");
      }
    }
  }

  function drawHProjection(data, imgW, imgH, color) {
    if (!data || data.length === 0) return;

    var maxVal = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i] != null && data[i] > maxVal) maxVal = data[i];
    }
    if (maxVal === 0) return;

    var height = imgH * settings.scale;
    var baseY = settings.h_side === "bottom" ? imgH : 0;
    var dir = settings.h_side === "bottom" ? -1 : 1;
    var step = imgW / data.length;

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(0, baseY);
    for (var i = 0; i < data.length; i++) {
      var val = data[i] != null ? data[i] : 0;
      var barH = (val / maxVal) * height;
      ctx.lineTo(i * step, baseY + dir * barH);
    }
    ctx.lineTo(imgW, baseY);
    ctx.closePath();
    ctx.fill();
  }

  function drawVProjection(data, imgW, imgH, color) {
    if (!data || data.length === 0) return;

    var maxVal = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i] != null && data[i] > maxVal) maxVal = data[i];
    }
    if (maxVal === 0) return;

    var width = imgW * settings.scale;
    var baseX = settings.v_side === "right" ? imgW : 0;
    var dir = settings.v_side === "right" ? -1 : 1;
    var step = imgH / data.length;

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(baseX, 0);
    for (var i = 0; i < data.length; i++) {
      var val = data[i] != null ? data[i] : 0;
      var barW = (val / maxVal) * width;
      ctx.lineTo(baseX + dir * barW, i * step);
    }
    ctx.lineTo(baseX, imgH);
    ctx.closePath();
    ctx.fill();
  }

  function drawHProjectionROI(data, roi, imgW, imgH, color) {
    if (!data || data.length === 0 || !roi) return;

    var maxVal = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i] != null && data[i] > maxVal) maxVal = data[i];
    }
    if (maxVal === 0) return;

    var height = imgH * settings.scale;
    var baseY = settings.h_side === "bottom" ? imgH : 0;
    var dir = settings.h_side === "bottom" ? -1 : 1;
    var roiW = roi.x1 - roi.x0;
    var step = roiW / data.length;

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(roi.x0, baseY);
    for (var i = 0; i < data.length; i++) {
      var val = data[i] != null ? data[i] : 0;
      var barH = (val / maxVal) * height;
      ctx.lineTo(roi.x0 + i * step, baseY + dir * barH);
    }
    ctx.lineTo(roi.x1, baseY);
    ctx.closePath();
    ctx.fill();
  }

  function drawVProjectionROI(data, roi, imgW, imgH, color) {
    if (!data || data.length === 0 || !roi) return;

    var maxVal = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i] != null && data[i] > maxVal) maxVal = data[i];
    }
    if (maxVal === 0) return;

    var width = imgW * settings.scale;
    var baseX = settings.v_side === "right" ? imgW : 0;
    var dir = settings.v_side === "right" ? -1 : 1;
    var roiH = roi.y1 - roi.y0;
    var step = roiH / data.length;

    ctx.fillStyle = color;
    ctx.beginPath();
    ctx.moveTo(baseX, roi.y0);
    for (var i = 0; i < data.length; i++) {
      var val = data[i] != null ? data[i] : 0;
      var barW = (val / maxVal) * width;
      ctx.lineTo(baseX + dir * barW, roi.y0 + i * step);
    }
    ctx.lineTo(baseX, roi.y1);
    ctx.closePath();
    ctx.fill();
  }

  // -- Crosshair at centroid reference --
  function drawCrosshair(msg) {
    if (!crosshairEnabled) return;

    var drift = msg.drift;
    if (!drift || !drift.has_reference || !drift.reference) return;

    var refX = drift.reference.x;
    var refY = drift.reference.y;
    var imgW = canvas.width;
    var imgH = canvas.height;

    ctx.strokeStyle = "rgba(255,255,255,0.6)";
    ctx.lineWidth = 1;
    ctx.setLineDash([6, 4]);

    // Vertical line through reference X
    ctx.beginPath();
    ctx.moveTo(refX + 0.5, 0);
    ctx.lineTo(refX + 0.5, imgH);
    ctx.stroke();

    // Horizontal line through reference Y
    ctx.beginPath();
    ctx.moveTo(0, refY + 0.5);
    ctx.lineTo(imgW, refY + 0.5);
    ctx.stroke();

    ctx.setLineDash([]);

    // Live centroid marker (small cross, solid)
    if (drift.live) {
      var lx = drift.live.x;
      var ly = drift.live.y;
      var arm = 8;

      ctx.strokeStyle = "rgba(0,173,181,0.9)";
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(lx - arm, ly);
      ctx.lineTo(lx + arm, ly);
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(lx, ly - arm);
      ctx.lineTo(lx, ly + arm);
      ctx.stroke();
    }
  }

  // -- Drift labels --
  function updateDriftLabel(msg) {
    if (!driftLabel) return;

    var drift = msg.drift;
    if (!drift || !drift.has_reference) {
      driftLabel.textContent = "\u0394x: --  \u0394y: --";
      return;
    }

    var dx = drift.drift_x;
    var dy = drift.drift_y;
    if (dx == null || dy == null) {
      driftLabel.textContent = "\u0394x: --  \u0394y: --";
      return;
    }

    var parts = "\u0394x: " + dx.toFixed(1) + " px  \u0394y: " + dy.toFixed(1) + " px";

    if (drift.drift_x_um != null && drift.drift_y_um != null) {
      var unit = (calibration && calibration.unit_label) ? calibration.unit_label : "\u00B5m";
      parts += "\n\u0394x: " + drift.drift_x_um.toFixed(1) + " " + unit +
               "  \u0394y: " + drift.drift_y_um.toFixed(1) + " " + unit;
    }

    driftLabel.textContent = parts;
    driftLabel.style.whiteSpace = "pre-line";
  }

  // -----------------------------------------------------------------------
  // Initialisation
  // -----------------------------------------------------------------------

  function fetchInitialState() {
    // Fetch overlay settings
    fetch(API_BASE + "/overlays")
      .then(function(r) { return r.json(); })
      .then(function(data) {
        for (var k in data) {
          if (data.hasOwnProperty(k) && settings.hasOwnProperty(k)) {
            settings[k] = data[k];
          }
        }
        syncControlsFromSettings();
      })
      .catch(function() {});

    // Fetch crosshair / drift state
    fetch(API_BASE + "/centroid")
      .then(function(r) { return r.json(); })
      .then(function(data) {
        crosshairEnabled = !!data.crosshair_enabled;
        crosshairToggle.classList.toggle("active", crosshairEnabled);
      })
      .catch(function() {});

    // Fetch calibration
    fetch(API_BASE + "/calibration")
      .then(function(r) { return r.json(); })
      .then(function(data) {
        calibration = data;
      })
      .catch(function() {});
  }

  function init() {
    buildControls();
    fetchInitialState();
  }

  // -----------------------------------------------------------------------
  // WS frame handler
  // -----------------------------------------------------------------------

  function updateFromFrame(msg) {
    lastMsg = msg;
    redraw();
  }

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------

  return {
    init: init,
    updateFromFrame: updateFromFrame,
  };

})();
