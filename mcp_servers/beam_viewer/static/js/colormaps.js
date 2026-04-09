"use strict";

/**
 * Colormap lookup tables -- 256-entry RGB Uint8Arrays.
 *
 * Each LUT is built by linearly interpolating between colour stops.
 * The grayscale pixel value (0-255) indexes directly into the LUT to
 * produce an (R, G, B) triple used when painting the canvas.
 */

function _buildLUT(stops) {
  var lut = new Uint8Array(256 * 3);
  for (var i = 0; i < 256; i++) {
    var t = i / 255;
    var lo = 0;
    for (var s = 1; s < stops.length; s++) {
      if (stops[s][0] >= t) { lo = s - 1; break; }
    }
    var hi = lo + 1;
    var range = stops[hi][0] - stops[lo][0];
    var f = range > 0 ? (t - stops[lo][0]) / range : 0;
    lut[i * 3]     = Math.round(stops[lo][1] + f * (stops[hi][1] - stops[lo][1]));
    lut[i * 3 + 1] = Math.round(stops[lo][2] + f * (stops[hi][2] - stops[lo][2]));
    lut[i * 3 + 2] = Math.round(stops[lo][3] + f * (stops[hi][3] - stops[lo][3]));
  }
  return lut;
}

// Exported as a global for use by other modules.
// Each key matches a VALID_COLORMAPS entry from the Python backend.
var COLORMAPS = {
  gray:    _buildLUT([[0,0,0,0],[1,255,255,255]]),
  hot:     _buildLUT([[0,0,0,0],[0.33,255,0,0],[0.66,255,255,0],[1,255,255,255]]),
  viridis: _buildLUT([[0,68,1,84],[0.25,59,82,139],[0.5,33,145,140],[0.75,94,201,98],[1,253,231,37]]),
  inferno: _buildLUT([[0,0,0,4],[0.25,87,16,110],[0.5,188,55,84],[0.75,249,142,9],[1,252,255,164]]),
  plasma:  _buildLUT([[0,13,8,135],[0.25,126,3,168],[0.5,204,71,120],[0.75,248,149,64],[1,240,249,33]]),
  magma:   _buildLUT([[0,0,0,4],[0.25,81,18,124],[0.5,183,55,121],[0.75,254,159,109],[1,252,253,191]]),
  cividis: _buildLUT([[0,0,32,77],[0.25,59,77,107],[0.5,124,123,120],[0.75,194,171,100],[1,255,234,70]]),
};
