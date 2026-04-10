"use strict";

/**
 * splitters.js — Drag-to-resize column splitters (matches PyQt QSplitter).
 *
 * Every <div class="splitter"> in the DOM becomes a draggable handle.
 * Dragging adjusts the pixel widths of the two adjacent flex siblings,
 * then converts all siblings back to proportional flex-grow values on
 * mouse-up so that window resizing scales columns proportionally.
 */

var Splitters = (function () {

  var MIN_WIDTH = 80;   // minimum column width (px)

  // -------------------------------------------------------------------
  // Helpers — find the visible flex siblings on either side of a splitter
  // -------------------------------------------------------------------
  function prevFlexSibling(el) {
    el = el.previousElementSibling;
    while (el) {
      if (!el.classList.contains("splitter") && el.style.display !== "none") return el;
      el = el.previousElementSibling;
    }
    return null;
  }

  function nextFlexSibling(el) {
    el = el.nextElementSibling;
    while (el) {
      if (!el.classList.contains("splitter") && el.style.display !== "none") return el;
      el = el.nextElementSibling;
    }
    return null;
  }

  // -------------------------------------------------------------------
  // Freeze all non-splitter visible children to their current pixel
  // widths (flex: 0 0 Npx) so dragging is precise.
  // -------------------------------------------------------------------
  function freezeWidths(container) {
    var children = container.children;
    for (var i = 0; i < children.length; i++) {
      var ch = children[i];
      if (ch.classList.contains("splitter")) continue;
      if (ch.style.display === "none") continue;
      var w = ch.getBoundingClientRect().width;
      ch.style.flex = "0 0 " + w + "px";
    }
  }

  // -------------------------------------------------------------------
  // Convert pixel widths back to proportional flex-grow values so
  // window resize scales all columns proportionally.
  // -------------------------------------------------------------------
  function unfreezeWidths(container) {
    var children = container.children;
    var totalW = 0;
    var items = [];

    for (var i = 0; i < children.length; i++) {
      var ch = children[i];
      if (ch.classList.contains("splitter")) continue;
      if (ch.style.display === "none") continue;
      var w = ch.getBoundingClientRect().width;
      totalW += w;
      items.push({ el: ch, width: w });
    }

    if (totalW === 0) return;

    for (var j = 0; j < items.length; j++) {
      var grow = (items[j].width / totalW) * 100;
      items[j].el.style.flex = grow + " 1 0px";
    }
  }

  // -------------------------------------------------------------------
  // Make a single splitter element draggable
  // -------------------------------------------------------------------
  function makeDraggable(splitter) {
    splitter.addEventListener("mousedown", function (e) {
      if (e.button !== 0) return;
      e.preventDefault();

      var left = prevFlexSibling(splitter);
      var right = nextFlexSibling(splitter);
      if (!left || !right) return;

      var container = splitter.parentElement;
      var startX = e.clientX;
      var leftW0 = left.getBoundingClientRect().width;
      var rightW0 = right.getBoundingClientRect().width;
      var sumW = leftW0 + rightW0;

      // Freeze all columns to pixels for precise dragging
      freezeWidths(container);

      document.body.classList.add("splitter-dragging");
      splitter.classList.add("active");

      function onMove(ev) {
        var dx = ev.clientX - startX;
        var newLeft = leftW0 + dx;
        var newRight = rightW0 - dx;

        // Enforce minimums
        if (newLeft < MIN_WIDTH) { newLeft = MIN_WIDTH; newRight = sumW - MIN_WIDTH; }
        if (newRight < MIN_WIDTH) { newRight = MIN_WIDTH; newLeft = sumW - MIN_WIDTH; }

        left.style.flex = "0 0 " + newLeft + "px";
        right.style.flex = "0 0 " + newRight + "px";
      }

      function onUp() {
        document.removeEventListener("mousemove", onMove);
        document.removeEventListener("mouseup", onUp);
        document.body.classList.remove("splitter-dragging");
        splitter.classList.remove("active");

        // Convert back to proportional so window resize scales columns
        unfreezeWidths(container);

        // Trigger canvas re-renders at new sizes
        window.dispatchEvent(new Event("resize"));
      }

      document.addEventListener("mousemove", onMove);
      document.addEventListener("mouseup", onUp);
    });
  }

  // -------------------------------------------------------------------
  // Initialise all splitters in the document
  // -------------------------------------------------------------------
  function init() {
    var splitters = document.querySelectorAll(".splitter");
    for (var i = 0; i < splitters.length; i++) {
      makeDraggable(splitters[i]);
    }
  }

  return { init: init };

})();
