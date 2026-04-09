"use strict";
/**
 * roi.js — Interactive Region-of-Interest overlay for beam viewer.
 *
 * Click-drag on the image canvas to draw an ROI rectangle.
 * On mouse-up the selection is sent to POST /roi.
 * Clear and Center buttons call DELETE /roi and POST /roi/center.
 * A secondary cropped image panel shows the ROI with projections.
 *
 * Expects DOM from index.html:
 *   - #beamCanvas inside .canvas-area
 *   - #controlPanel sidebar (ROI section appended there)
 *
 * Public API (attached to window.BeamROI):
 *   - updateFromFrame(roiData)  — called each WS frame with msg.roi
 */
var BeamROI = (function () {
  // -----------------------------------------------------------------------
  // Helper
  // -----------------------------------------------------------------------
  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text) e.textContent = text;
    return e;
  }

  // -----------------------------------------------------------------------
  // DOM references
  // -----------------------------------------------------------------------
  var canvas = document.getElementById("beamCanvas");
  var canvasArea = canvas.closest(".canvas-area");
  var panel = document.getElementById("controlPanel");

  // Overlay canvas for ROI rectangle (same pixel size as beam canvas)
  var overlay = document.createElement("canvas");
  overlay.id = "roiOverlay";
  overlay.style.cssText =
    "position:absolute;top:0;left:0;width:100%;height:100%;" +
    "pointer-events:none;image-rendering:pixelated;";
  canvasArea.appendChild(overlay);
  var octx = overlay.getContext("2d");

  // -----------------------------------------------------------------------
  // Inject ROI-specific styles (complement cp-* classes from theme.css)
  // -----------------------------------------------------------------------
  var style = document.createElement("style");
  style.textContent =
    ".roi-info { color:var(--text-dim); font-size:11px; flex:1; text-align:right; }" +
    ".roi-preview { margin-top:6px; display:flex; gap:4px; align-items:flex-start; }" +
    ".roi-preview canvas { background:var(--image-bg); image-rendering:pixelated; display:block; }" +
    ".roi-proj-col { display:flex; flex-direction:column; gap:4px; }" +
    ".roi-xproj-wrap { margin-top:4px; }";
  document.head.appendChild(style);

  // -----------------------------------------------------------------------
  // Build ROI section in control panel (uses cp-section pattern)
  // -----------------------------------------------------------------------
  var section = el("div", "cp-section");

  // Collapsible header
  var header = el("div", "cp-section-header");
  var chevron = el("span", "cp-chevron", "\u25BE");
  header.appendChild(chevron);
  header.appendChild(document.createTextNode(" ROI"));
  header.addEventListener("click", function () {
    if (body.style.display === "none") {
      body.style.display = "";
      chevron.textContent = "\u25BE";
    } else {
      body.style.display = "none";
      chevron.textContent = "\u25B8";
    }
  });
  section.appendChild(header);

  // Section body
  var body = el("div", "cp-section-body");

  // Controls row: Clear / Center / info
  var btnRow = el("div", "cp-btn-row");
  var clearBtn = el("button", "cp-btn", "Clear");
  clearBtn.disabled = true;
  var centerBtn = el("button", "cp-btn", "Center");
  centerBtn.disabled = true;
  var roiInfo = el("span", "roi-info", "Draw on image");
  btnRow.appendChild(clearBtn);
  btnRow.appendChild(centerBtn);
  btnRow.appendChild(roiInfo);
  body.appendChild(btnRow);

  // Preview area (hidden until ROI is active)
  var previewWrap = el("div", "roi-preview");
  previewWrap.style.display = "none";
  var roiCanvas = document.createElement("canvas");
  roiCanvas.width = 200;
  roiCanvas.height = 200;
  var projCol = el("div", "roi-proj-col");
  var roiProjYCanvas = document.createElement("canvas");
  roiProjYCanvas.width = 50;
  roiProjYCanvas.height = 200;
  projCol.appendChild(roiProjYCanvas);
  previewWrap.appendChild(roiCanvas);
  previewWrap.appendChild(projCol);
  body.appendChild(previewWrap);

  // X projection below the preview
  var xProjWrap = el("div", "roi-xproj-wrap");
  xProjWrap.style.display = "none";
  var roiProjXCanvas = document.createElement("canvas");
  roiProjXCanvas.width = 200;
  roiProjXCanvas.height = 50;
  xProjWrap.appendChild(roiProjXCanvas);
  body.appendChild(xProjWrap);

  section.appendChild(body);
  panel.appendChild(section);

  var roiCtx = roiCanvas.getContext("2d");
  var roiProjXCtx = roiProjXCanvas.getContext("2d");
  var roiProjYCtx = roiProjYCanvas.getContext("2d");

  // -----------------------------------------------------------------------
  // State
  // -----------------------------------------------------------------------
  var currentROI = null; // {x0, y0, x1, y1} in image pixels
  var dragging = false;
  var dragStart = null;
  var dragEnd = null;

  // -----------------------------------------------------------------------
  // Coordinate helpers
  // -----------------------------------------------------------------------
  function mouseToImageCoords(e) {
    var rect = canvas.getBoundingClientRect();
    var scaleX = canvas.width / rect.width;
    var scaleY = canvas.height / rect.height;
    return {
      x: Math.round((e.clientX - rect.left) * scaleX),
      y: Math.round((e.clientY - rect.top) * scaleY),
    };
  }

  function clamp(v, lo, hi) {
    return v < lo ? lo : v > hi ? hi : v;
  }

  function normalizeRect(a, b) {
    return {
      x0: Math.min(a.x, b.x),
      y0: Math.min(a.y, b.y),
      x1: Math.max(a.x, b.x),
      y1: Math.max(a.y, b.y),
    };
  }

  // -----------------------------------------------------------------------
  // Draw ROI rectangle on overlay canvas
  // -----------------------------------------------------------------------
  function syncOverlaySize() {
    if (overlay.width !== canvas.width || overlay.height !== canvas.height) {
      overlay.width = canvas.width;
      overlay.height = canvas.height;
    }
  }

  function drawROI() {
    syncOverlaySize();
    octx.clearRect(0, 0, overlay.width, overlay.height);

    var roi =
      dragging && dragStart && dragEnd
        ? normalizeRect(dragStart, dragEnd)
        : currentROI;
    if (!roi) return;

    var w = roi.x1 - roi.x0;
    var h = roi.y1 - roi.y0;
    if (w < 1 || h < 1) return;

    // Semi-transparent fill
    octx.fillStyle = "rgba(0, 173, 181, 0.12)"; // accent at low opacity
    octx.fillRect(roi.x0, roi.y0, w, h);

    // Dashed border in accent colour
    octx.strokeStyle = "rgba(0, 173, 181, 0.8)";
    octx.lineWidth = 1;
    octx.setLineDash([4, 3]);
    octx.strokeRect(roi.x0 + 0.5, roi.y0 + 0.5, w - 1, h - 1);
    octx.setLineDash([]);
  }

  // -----------------------------------------------------------------------
  // Mouse interaction on the canvas area
  // -----------------------------------------------------------------------
  function onMouseDown(e) {
    if (e.button !== 0) return;
    var pos = mouseToImageCoords(e);
    pos.x = clamp(pos.x, 0, canvas.width - 1);
    pos.y = clamp(pos.y, 0, canvas.height - 1);
    dragging = true;
    dragStart = pos;
    dragEnd = pos;
    e.preventDefault();
  }

  function onMouseMove(e) {
    if (!dragging) return;
    var pos = mouseToImageCoords(e);
    pos.x = clamp(pos.x, 0, canvas.width - 1);
    pos.y = clamp(pos.y, 0, canvas.height - 1);
    dragEnd = pos;
    drawROI();
  }

  function onMouseUp(e) {
    if (!dragging) return;
    dragging = false;
    var pos = mouseToImageCoords(e);
    pos.x = clamp(pos.x, 0, canvas.width - 1);
    pos.y = clamp(pos.y, 0, canvas.height - 1);
    dragEnd = pos;

    var rect = normalizeRect(dragStart, dragEnd);
    var w = rect.x1 - rect.x0;
    var h = rect.y1 - rect.y0;

    // Ignore tiny drags (accidental clicks)
    if (w < 4 || h < 4) {
      dragStart = null;
      dragEnd = null;
      drawROI();
      return;
    }

    sendROI(rect);
    dragStart = null;
    dragEnd = null;
  }

  canvasArea.addEventListener("mousedown", onMouseDown);
  canvasArea.addEventListener("mousemove", onMouseMove);
  window.addEventListener("mouseup", onMouseUp);

  // -----------------------------------------------------------------------
  // API calls
  // -----------------------------------------------------------------------
  function sendROI(rect) {
    fetch("../roi", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        x0: rect.x0,
        y0: rect.y0,
        x1: rect.x1,
        y1: rect.y1,
      }),
    }).catch(function () {});
  }

  clearBtn.addEventListener("click", function () {
    fetch("../roi", { method: "DELETE" }).catch(function () {});
  });

  centerBtn.addEventListener("click", function () {
    fetch("../roi/center", { method: "POST" }).catch(function () {});
  });

  // -----------------------------------------------------------------------
  // Update from WS frame data
  // -----------------------------------------------------------------------
  function updateFromFrame(roiData) {
    if (!roiData || !roiData.active) {
      currentROI = null;
      clearBtn.disabled = true;
      centerBtn.disabled = true;
      roiInfo.textContent = "Draw on image";
      previewWrap.style.display = "none";
      xProjWrap.style.display = "none";
      drawROI();
      return;
    }

    var r = roiData.roi;
    currentROI = { x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
    clearBtn.disabled = false;
    centerBtn.disabled = false;

    var w = r.x1 - r.x0;
    var h = r.y1 - r.y0;
    roiInfo.textContent = w + "\u00d7" + h + " @ (" + r.x0 + "," + r.y0 + ")";

    drawROI();
    fetchROIFrame();
  }

  // -----------------------------------------------------------------------
  // Fetch and render ROI cropped frame
  // -----------------------------------------------------------------------
  var roiFetchPending = false;

  function fetchROIFrame() {
    if (roiFetchPending) return;
    roiFetchPending = true;

    fetch("../frames/roi")
      .then(function (r) {
        return r.json();
      })
      .then(function (data) {
        roiFetchPending = false;
        if (!data.active || !data.metadata) {
          previewWrap.style.display = "none";
          xProjWrap.style.display = "none";
          return;
        }
        previewWrap.style.display = "";
        xProjWrap.style.display = "";

        if (data.image_b64_png) {
          renderROIImage(data.image_b64_png);
        }
        if (data.projections) {
          renderProjX(data.projections.x_projection);
          renderProjY(data.projections.y_projection);
        }
      })
      .catch(function () {
        roiFetchPending = false;
      });
  }

  function renderROIImage(pngB64) {
    var img = new Image();
    img.onload = function () {
      roiCanvas.width = img.naturalWidth;
      roiCanvas.height = img.naturalHeight;
      roiCtx.drawImage(img, 0, 0);
    };
    img.src = "data:image/png;base64," + pngB64;
  }

  function renderProjX(data) {
    if (!data || data.length === 0) return;
    var w = Math.min(data.length, 240);
    var h = 50;
    roiProjXCanvas.width = w;
    roiProjXCanvas.height = h;
    roiProjXCtx.clearRect(0, 0, w, h);

    var max = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i] > max) max = data[i];
    }
    if (max === 0) return;

    var step = data.length / w;
    roiProjXCtx.fillStyle = "var(--h-curve, rgba(0,229,255,0.6))";
    for (var i = 0; i < w; i++) {
      var idx = Math.floor(i * step);
      var barH = (data[idx] / max) * h;
      roiProjXCtx.fillRect(i, h - barH, 1, barH);
    }
  }

  function renderProjY(data) {
    if (!data || data.length === 0) return;
    var w = 50;
    var h = Math.min(data.length, 240);
    roiProjYCanvas.width = w;
    roiProjYCanvas.height = h;
    roiProjYCtx.clearRect(0, 0, w, h);

    var max = 0;
    for (var i = 0; i < data.length; i++) {
      if (data[i] > max) max = data[i];
    }
    if (max === 0) return;

    var step = data.length / h;
    roiProjYCtx.fillStyle = "var(--v-curve, rgba(206,147,216,0.6))";
    for (var i = 0; i < h; i++) {
      var idx = Math.floor(i * step);
      var barW = (data[idx] / max) * w;
      roiProjYCtx.fillRect(0, i, barW, 1);
    }
  }

  // -----------------------------------------------------------------------
  // Load initial ROI state from server
  // -----------------------------------------------------------------------
  fetch("../roi")
    .then(function (r) {
      return r.json();
    })
    .then(function (data) {
      updateFromFrame(data);
    })
    .catch(function () {});

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------
  return {
    updateFromFrame: updateFromFrame,
  };
})();
