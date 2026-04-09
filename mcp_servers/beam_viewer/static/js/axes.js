"use strict";

/**
 * axes.js — Pixel-coordinate axis overlays for the full image and ROI image.
 *
 * The axis canvas is sized to the CSS display dimensions of the container
 * (not the image pixel dimensions), so text and tick marks are always drawn
 * at native screen resolution and never scaled up or pixelated.
 *
 * The image's actual position within the container is found via
 * getBoundingClientRect(), so axes are always aligned to the rendered image
 * regardless of CSS zoom level or letterboxing.
 *
 * Public API:
 *   Axes.updateMain(width, height)       — call after full-image render
 *   Axes.updateROI(x0, y0, x1, y1)      — call after ROI image render
 */

var Axes = (function () {

  // Sizes in CSS pixels (drawn at native resolution — no scaling needed)
  var FONT_PX  = 9;
  var TICK_LEN = 4;
  var PAD      = 2;
  var MARG_H   = 20;  // bottom strip height for X-axis labels
  var MARG_V   = 42;  // left strip width for Y-axis labels

  // -----------------------------------------------------------------------
  // Nice tick step targeting ~5-6 ticks for the given range
  // -----------------------------------------------------------------------
  function niceStep(range) {
    if (range === 0) return 1;
    var rawStep = range / 6;
    var mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    var factors = [1, 2, 2.5, 5, 10];
    for (var i = 0; i < factors.length; i++) {
      if (factors[i] * mag >= rawStep) return factors[i] * mag;
    }
    return 10 * mag;
  }

  // -----------------------------------------------------------------------
  // Create axis overlay canvas — sized to CSS display, not image pixels
  // -----------------------------------------------------------------------
  function createAxisCanvas(areaEl) {
    var c = document.createElement("canvas");
    // z-index 4: above the image, below ROI rectangle and projection overlays
    c.style.cssText =
      "position:absolute;top:0;left:0;width:100%;height:100%;" +
      "pointer-events:none;z-index:4;";
    areaEl.appendChild(c);
    return c;
  }

  // -----------------------------------------------------------------------
  // Draw axes at native CSS resolution
  // -----------------------------------------------------------------------
  function drawAxes(axisCanvas, imgEl, xMin, xMax, yMin, yMax) {
    var area = axisCanvas.parentElement;
    var areaW = area.clientWidth;
    var areaH = area.clientHeight;
    if (areaW === 0 || areaH === 0) return;

    // Size backing store to CSS display dimensions — crisp at any zoom
    if (axisCanvas.width !== areaW)  axisCanvas.width  = areaW;
    if (axisCanvas.height !== areaH) axisCanvas.height = areaH;

    var ctx = axisCanvas.getContext("2d");
    ctx.clearRect(0, 0, areaW, areaH);

    // Locate the image within the container (handles letterboxing + scaling)
    var imgRect  = imgEl.getBoundingClientRect();
    var areaRect = area.getBoundingClientRect();
    var imgLeft  = imgRect.left - areaRect.left;
    var imgTop   = imgRect.top  - areaRect.top;
    var imgW     = imgRect.width;
    var imgH     = imgRect.height;
    if (imgW === 0 || imgH === 0) return;

    // Plot region inside the image (axis strips at bottom and left edges)
    var plotLeft   = imgLeft + MARG_V;
    var plotRight  = imgLeft + imgW;
    var plotTop    = imgTop;
    var plotBottom = imgTop  + imgH - MARG_H;
    var plotW      = plotRight  - plotLeft;
    var plotH      = plotBottom - plotTop;
    if (plotW <= 0 || plotH <= 0) return;

    // Semi-transparent dark background behind labels
    ctx.fillStyle = "rgba(0,0,0,0.6)";
    ctx.fillRect(imgLeft, imgTop,          MARG_V, imgH);  // left strip
    ctx.fillRect(imgLeft, plotBottom,      imgW,   MARG_H); // bottom strip

    ctx.font      = FONT_PX + "px monospace";
    ctx.lineWidth = 1;

    // ---- X axis (bottom of image) ----
    var xRange = xMax - xMin;
    var xStep  = niceStep(xRange);

    ctx.strokeStyle = "rgba(255,255,255,0.65)";
    ctx.fillStyle   = "rgba(255,255,255,0.85)";

    ctx.beginPath();
    ctx.moveTo(plotLeft,  plotBottom + 0.5);
    ctx.lineTo(plotRight, plotBottom + 0.5);
    ctx.stroke();

    ctx.textAlign    = "center";
    ctx.textBaseline = "top";

    var firstX = Math.ceil(xMin / xStep) * xStep;
    for (var px = firstX; px < xMax; px += xStep) {
      var dx = plotLeft + (px - xMin) / xRange * plotW;
      ctx.beginPath();
      ctx.moveTo(dx + 0.5, plotBottom);
      ctx.lineTo(dx + 0.5, plotBottom + TICK_LEN);
      ctx.stroke();
      ctx.fillText(String(px), dx, plotBottom + TICK_LEN + PAD);
    }

    // ---- Y axis (left of image) ----
    var yRange = yMax - yMin;
    var yStep  = niceStep(yRange);

    ctx.beginPath();
    ctx.moveTo(plotLeft - 0.5, plotTop);
    ctx.lineTo(plotLeft - 0.5, plotBottom);
    ctx.stroke();

    ctx.textAlign    = "right";
    ctx.textBaseline = "middle";

    var firstY = Math.ceil(yMin / yStep) * yStep;
    for (var py = firstY; py < yMax; py += yStep) {
      var dy = plotTop + (py - yMin) / yRange * plotH;
      ctx.beginPath();
      ctx.moveTo(plotLeft,            dy + 0.5);
      ctx.lineTo(plotLeft - TICK_LEN, dy + 0.5);
      ctx.stroke();
      ctx.fillText(String(py), plotLeft - TICK_LEN - PAD, dy);
    }
  }

  // -----------------------------------------------------------------------
  // Per-canvas setup
  // -----------------------------------------------------------------------
  var mainCanvas  = document.getElementById("beamCanvas");
  var roiCanvasEl = document.getElementById("roiCanvas");
  var roiArea     = roiCanvasEl ? roiCanvasEl.closest(".canvas-area") : null;

  var mainAxisCanvas = createAxisCanvas(mainCanvas.closest(".canvas-area"));
  var roiAxisCanvas  = roiArea ? createAxisCanvas(roiArea) : null;

  var mainState = null;
  var roiState  = null;

  // -----------------------------------------------------------------------
  // Public API
  // -----------------------------------------------------------------------
  function updateMain(width, height) {
    mainState = { xMin: 0, xMax: width, yMin: 0, yMax: height };
    requestAnimationFrame(function () {
      drawAxes(mainAxisCanvas, mainCanvas, 0, width, 0, height);
    });
  }

  function updateROI(x0, y0, x1, y1) {
    if (!roiAxisCanvas) return;
    roiState = { xMin: x0, xMax: x1, yMin: y0, yMax: y1 };
    requestAnimationFrame(function () {
      drawAxes(roiAxisCanvas, roiCanvasEl, x0, x1, y0, y1);
    });
  }

  window.addEventListener("resize", function () {
    requestAnimationFrame(function () {
      if (mainState) {
        drawAxes(mainAxisCanvas, mainCanvas,
          mainState.xMin, mainState.xMax, mainState.yMin, mainState.yMax);
      }
      if (roiAxisCanvas && roiState) {
        drawAxes(roiAxisCanvas, roiCanvasEl,
          roiState.xMin, roiState.xMax, roiState.yMin, roiState.yMax);
      }
    });
  });

  return {
    updateMain: updateMain,
    updateROI:  updateROI,
  };

})();
