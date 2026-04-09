"use strict";
/**
 * roi.js — Interactive Region-of-Interest for beam viewer.
 *
 * Click-drag on the full image canvas to draw an ROI rectangle.
 * On mouse-up the selection is sent to POST /roi.
 * Clear/Center buttons are in the Analysis section (controls.js).
 *
 * When an ROI is active, the ROI image pane and ROI projection areas
 * in the main viewer are shown (matching the PyQt layout where
 * image_pane_2, h_proj_2, v_proj_2 become visible).
 *
 * Public API (attached to window.BeamROI):
 *   - updateFromFrame(roiData)  — called each WS frame with msg.roi
 */
var BeamROI = (function () {
  // -----------------------------------------------------------------------
  // DOM references — main viewer panes
  // -----------------------------------------------------------------------
  var canvas = document.getElementById("beamCanvas");
  var canvasArea = canvas.closest(".canvas-area");

  // ROI viewer panes (in main layout, hidden by default)
  var roiImagePane = document.getElementById("roiImagePane");
  var roiCanvas = document.getElementById("roiCanvas");
  var roiHProjArea = document.getElementById("roiHProjArea");
  var roiVProjArea = document.getElementById("roiVProjArea");
  var roiHProjCanvas = document.getElementById("roiHProjCanvas");
  var roiVProjCanvas = document.getElementById("roiVProjCanvas");

  var roiCtx = roiCanvas ? roiCanvas.getContext("2d") : null;

  // Overlay canvas for ROI rectangle on full image
  var overlay = document.createElement("canvas");
  overlay.id = "roiOverlay";
  overlay.style.cssText =
    "position:absolute;top:0;left:0;width:100%;height:100%;" +
    "pointer-events:none;image-rendering:pixelated;";
  canvasArea.appendChild(overlay);
  var octx = overlay.getContext("2d");

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
    octx.fillStyle = "rgba(0, 173, 181, 0.12)";
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

  // -----------------------------------------------------------------------
  // Show/hide ROI panes in main viewer (like PyQt show/hide)
  // -----------------------------------------------------------------------
  function showROIPanes() {
    if (roiImagePane) roiImagePane.style.display = "flex";
    if (roiHProjArea) roiHProjArea.style.display = "block";
    if (roiVProjArea) roiVProjArea.style.display = "block";
  }

  function hideROIPanes() {
    if (roiImagePane) roiImagePane.style.display = "none";
    if (roiHProjArea) roiHProjArea.style.display = "none";
    if (roiVProjArea) roiVProjArea.style.display = "none";
  }

  // -----------------------------------------------------------------------
  // Sync control panel ROI buttons (Clear / Center in Analysis section)
  // -----------------------------------------------------------------------
  function syncRoiButtons(hasROI) {
    if (typeof ControlPanel !== "undefined") {
      if (ControlPanel.clearRoiBtn) ControlPanel.clearRoiBtn.disabled = !hasROI;
      if (ControlPanel.centerRoiBtn) ControlPanel.centerRoiBtn.disabled = !hasROI;
    }
  }

  // -----------------------------------------------------------------------
  // Update from WS frame data
  // -----------------------------------------------------------------------
  function updateFromFrame(roiData) {
    if (!roiData || !roiData.active) {
      currentROI = null;
      syncRoiButtons(false);
      hideROIPanes();
      drawROI();
      return;
    }

    var r = roiData.roi;
    currentROI = { x0: r.x0, y0: r.y0, x1: r.x1, y1: r.y1 };
    syncRoiButtons(true);
    showROIPanes();
    drawROI();
    fetchROIFrame();
  }

  // -----------------------------------------------------------------------
  // Fetch and render ROI cropped frame + projections
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
          hideROIPanes();
          return;
        }

        if (data.image_b64_png) {
          renderROIImage(data.image_b64_png);
        }
        if (data.projections) {
          // Render ROI projections via the Projections module
          if (typeof Projections !== "undefined" && Projections.updateROI) {
            Projections.updateROI(data.projections);
          }
        }
      })
      .catch(function () {
        roiFetchPending = false;
      });
  }

  function renderROIImage(pngB64) {
    if (!roiCtx) return;
    var img = new Image();
    img.onload = function () {
      var w = img.naturalWidth;
      var h = img.naturalHeight;
      roiCanvas.width  = w;
      roiCanvas.height = h;

      // Apply the same colormap LUT as the main image
      var off    = new OffscreenCanvas(w, h);
      var offCtx = off.getContext("2d");
      offCtx.drawImage(img, 0, 0);
      var src  = offCtx.getImageData(0, 0, w, h).data;
      var cmap = (typeof Renderer !== "undefined") ? Renderer.getCmap() : "hot";
      var lut  = COLORMAPS[cmap] || COLORMAPS.gray;
      var out  = roiCtx.createImageData(w, h);
      var d    = out.data;
      for (var i = 0, j = 0; i < src.length; i += 4, j++) {
        var l = src[i] * 3;          // src is grayscale: R=G=B
        d[j*4]     = lut[l];
        d[j*4 + 1] = lut[l + 1];
        d[j*4 + 2] = lut[l + 2];
        d[j*4 + 3] = 255;
      }
      roiCtx.putImageData(out, 0, 0);

      if (typeof Axes !== "undefined" && currentROI) {
        Axes.updateROI(currentROI.x0, currentROI.y0, currentROI.x1, currentROI.y1);
      }
    };
    img.src = "data:image/png;base64," + pngB64;
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
