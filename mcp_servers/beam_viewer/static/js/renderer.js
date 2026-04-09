"use strict";

/**
 * Canvas renderer -- decodes JPEG frames and applies a colormap LUT.
 *
 * Uses an OffscreenCanvas to decode the JPEG, extracts the red channel
 * (browsers decode grayscale JPEG as identical R=G=B), then paints the
 * colormapped result onto the visible canvas.
 */

var Renderer = (function() {
  var canvas = document.getElementById("beamCanvas");
  var ctx    = canvas.getContext("2d");
  var _currentCmap = "hot";

  function applyColormap(grayPixels, width, height, cmapName) {
    canvas.width  = width;
    canvas.height = height;
    var imgData = ctx.createImageData(width, height);
    var lut = COLORMAPS[cmapName] || COLORMAPS.gray;
    var d = imgData.data;
    for (var i = 0, len = grayPixels.length; i < len; i++) {
      var v = grayPixels[i];
      var o = i * 4;
      var l = v * 3;
      d[o]     = lut[l];
      d[o + 1] = lut[l + 1];
      d[o + 2] = lut[l + 2];
      d[o + 3] = 255;
    }
    ctx.putImageData(imgData, 0, 0);
    if (typeof Axes !== "undefined") {
      Axes.updateMain(width, height);
    }
  }

  function renderFrame(jpegB64, cmapName) {
    _currentCmap = cmapName;
    var img = new Image();
    img.onload = function() {
      var w = img.naturalWidth;
      var h = img.naturalHeight;
      var off    = new OffscreenCanvas(w, h);
      var offCtx = off.getContext("2d");
      offCtx.drawImage(img, 0, 0);
      var src = offCtx.getImageData(0, 0, w, h).data;

      var gray = new Uint8Array(w * h);
      for (var i = 0, j = 0; i < src.length; i += 4, j++) {
        gray[j] = src[i];
      }
      applyColormap(gray, w, h, cmapName);
    };
    img.src = "data:image/jpeg;base64," + jpegB64;
  }

  return {
    renderFrame: renderFrame,
    getCmap: function() { return _currentCmap; },
  };
})();
