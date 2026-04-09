"use strict";

/**
 * Right-side control panel -- Camera, Acquisition, Background, Analysis, Display.
 *
 * Each section is collapsible.  Controls call REST endpoints on change
 * and are kept in sync via WebSocket payload readback.
 */

var ControlPanel = (function() {

  // -----------------------------------------------------------------------
  // Helpers
  // -----------------------------------------------------------------------
  var API_BASE = "..";  // panel is mounted at /panel/, API at /

  function api(path, opts) {
    return fetch(API_BASE + path, opts);
  }

  function postJSON(path, body) {
    return api(path, {
      method: "POST",
      headers: {"Content-Type": "application/json"},
      body: JSON.stringify(body),
    });
  }

  function post(path) {
    return api(path, {method: "POST"});
  }

  // Create a collapsible section with a header and content area.
  function makeSection(title, parentEl) {
    var section = document.createElement("div");
    section.className = "cp-section";

    var header = document.createElement("div");
    header.className = "cp-section-header";

    var chevron = document.createElement("span");
    chevron.className = "cp-chevron";
    chevron.textContent = "\u25BE";  // down-pointing triangle

    header.appendChild(chevron);
    header.appendChild(document.createTextNode(" " + title));

    header.addEventListener("click", function() {
      var body = section.querySelector(".cp-section-body");
      if (body.style.display === "none") {
        body.style.display = "";
        chevron.textContent = "\u25BE";
      } else {
        body.style.display = "none";
        chevron.textContent = "\u25B8";
      }
    });
    section.appendChild(header);

    var body = document.createElement("div");
    body.className = "cp-section-body";
    section.appendChild(body);

    parentEl.appendChild(section);
    return body;
  }

  function makeRow(label, parentEl) {
    var row = document.createElement("div");
    row.className = "cp-row";
    if (label) {
      var lbl = document.createElement("label");
      lbl.className = "cp-label";
      lbl.textContent = label;
      row.appendChild(lbl);
    }
    parentEl.appendChild(row);
    return row;
  }

  function makeToggleButton(text, parentEl, opts) {
    opts = opts || {};
    var btn = document.createElement("button");
    btn.className = "cp-btn cp-toggle" + (opts.active ? " active" : "");
    btn.textContent = text;
    if (opts.disabled) btn.disabled = true;
    parentEl.appendChild(btn);
    return btn;
  }

  function makeButton(text, parentEl, opts) {
    opts = opts || {};
    var btn = document.createElement("button");
    btn.className = "cp-btn" + (opts.cls ? " " + opts.cls : "");
    btn.textContent = text;
    if (opts.disabled) btn.disabled = true;
    parentEl.appendChild(btn);
    return btn;
  }

  function clearChildren(el) {
    while (el.firstChild) el.removeChild(el.firstChild);
  }

  // -----------------------------------------------------------------------
  // Panel DOM
  // -----------------------------------------------------------------------
  var panel = document.getElementById("controlPanel");
  if (!panel) return {};  // bail if container not present

  // -- Camera section -----------------------------------------------------
  var camBody = makeSection("Camera Setup", panel);

  var prefixRow = makeRow("Camera:", camBody);
  var prefixSelect = document.createElement("select");
  prefixSelect.className = "cp-select";
  prefixRow.appendChild(prefixSelect);

  var expRow = makeRow("Exposure (s):", camBody);
  var exposureInput = document.createElement("input");
  exposureInput.type = "number";
  exposureInput.className = "cp-input";
  exposureInput.min = "0.0001";
  exposureInput.max = "30";
  exposureInput.step = "0.01";
  exposureInput.value = "0.1";
  expRow.appendChild(exposureInput);
  var exposureBtn = makeButton("Set", expRow);

  var gainRow = makeRow("Gain:", camBody);
  var gainInput = document.createElement("input");
  gainInput.type = "number";
  gainInput.className = "cp-input";
  gainInput.min = "0";
  gainInput.max = "40";
  gainInput.step = "1";
  gainInput.value = "0";
  gainRow.appendChild(gainInput);
  var gainBtn = makeButton("Set", gainRow);

  // -- Acquisition section ------------------------------------------------
  var acqBody = makeSection("Acquisition", panel);

  var streamBtn = makeToggleButton("Streaming", acqBody, {active: true});

  var fitRow = document.createElement("div");
  fitRow.className = "cp-btn-row";
  acqBody.appendChild(fitRow);
  var fitFullBtn = makeToggleButton("Fit Full", fitRow, {active: true});
  var fitRoiBtn = makeToggleButton("Fit ROI", fitRow);

  // -- Background section -------------------------------------------------
  var bgBody = makeSection("Background", panel);

  var acquireBgBtn = makeButton("Acquire Background", bgBody);

  var bgSubBtn = makeToggleButton("Background Sub", bgBody, {disabled: true});

  var bgStatus = document.createElement("div");
  bgStatus.className = "cp-status-text";
  bgStatus.textContent = "BG: none";
  bgBody.appendChild(bgStatus);

  var bgIoRow = document.createElement("div");
  bgIoRow.className = "cp-btn-row";
  bgBody.appendChild(bgIoRow);
  var saveBgBtn = makeButton("Save BG", bgIoRow, {disabled: true});
  var loadBgBtn = makeButton("Load BG", bgIoRow);

  // File list for loading backgrounds (hidden by default)
  var bgFileWrap = document.createElement("div");
  bgFileWrap.className = "cp-bg-file-list";
  bgFileWrap.style.display = "none";
  bgBody.appendChild(bgFileWrap);
  var bgFileSelect = document.createElement("select");
  bgFileSelect.className = "cp-select";
  bgFileSelect.size = 4;
  bgFileWrap.appendChild(bgFileSelect);
  var bgFileLoadBtn = makeButton("Load Selected", bgFileWrap);

  // -- Display section ----------------------------------------------------
  var dispBody = makeSection("Display", panel);

  var cmapRow = makeRow("Colormap:", dispBody);
  var cmapSelect = document.createElement("select");
  cmapSelect.className = "cp-select";
  var cmapOptions = ["hot", "viridis", "inferno", "plasma", "magma", "cividis", "gray"];
  cmapOptions.forEach(function(name) {
    var opt = document.createElement("option");
    opt.value = name;
    opt.textContent = name;
    cmapSelect.appendChild(opt);
  });
  cmapSelect.value = "hot";
  cmapRow.appendChild(cmapSelect);

  var crosshairBtn = makeToggleButton("Show Crosshair", dispBody);

  // -----------------------------------------------------------------------
  // Event handlers
  // -----------------------------------------------------------------------

  // Camera prefix
  prefixSelect.addEventListener("change", function() {
    postJSON("/camera/prefix", {prefix: prefixSelect.value}).catch(function() {});
  });

  // Exposure
  exposureBtn.addEventListener("click", function() {
    var val = parseFloat(exposureInput.value);
    if (isNaN(val)) return;
    postJSON("/camera/exposure", {value: val}).catch(function() {});
  });

  // Gain
  gainBtn.addEventListener("click", function() {
    var val = parseInt(gainInput.value, 10);
    if (isNaN(val)) return;
    postJSON("/camera/gain", {value: val}).catch(function() {});
  });

  // Streaming toggle
  streamBtn.addEventListener("click", function() {
    var nowActive = streamBtn.classList.contains("active");
    postJSON("/streaming", {streaming: !nowActive}).then(function() {
      streamBtn.classList.toggle("active");
    }).catch(function() {});
  });

  // Fit Full toggle
  fitFullBtn.addEventListener("click", function() {
    var nowActive = fitFullBtn.classList.contains("active");
    postJSON("/analysis/fit-full", {enabled: !nowActive}).then(function() {
      fitFullBtn.classList.toggle("active");
    }).catch(function() {});
  });

  // Fit ROI toggle
  fitRoiBtn.addEventListener("click", function() {
    var nowActive = fitRoiBtn.classList.contains("active");
    postJSON("/analysis/fit-roi", {enabled: !nowActive}).then(function() {
      fitRoiBtn.classList.toggle("active");
    }).catch(function() {});
  });

  // Acquire background
  acquireBgBtn.addEventListener("click", function() {
    post("/background/acquire").catch(function() {});
  });

  // Background subtraction toggle
  bgSubBtn.addEventListener("click", function() {
    var nowActive = bgSubBtn.classList.contains("active");
    postJSON("/background/subtraction", {enabled: !nowActive}).then(function() {
      bgSubBtn.classList.toggle("active");
    }).catch(function() {});
  });

  // Save background
  saveBgBtn.addEventListener("click", function() {
    post("/background/save").catch(function() {});
  });

  // Load background — show file list
  loadBgBtn.addEventListener("click", function() {
    var visible = bgFileWrap.style.display !== "none";
    if (visible) {
      bgFileWrap.style.display = "none";
      return;
    }
    api("/background/list").then(function(r) { return r.json(); }).then(function(data) {
      clearChildren(bgFileSelect);
      (data.backgrounds || []).forEach(function(bg) {
        var opt = document.createElement("option");
        opt.value = bg.path;
        opt.textContent = bg.filename;
        bgFileSelect.appendChild(opt);
      });
      bgFileWrap.style.display = "";
    }).catch(function() {});
  });

  // Load selected background file
  bgFileLoadBtn.addEventListener("click", function() {
    var path = bgFileSelect.value;
    if (!path) return;
    postJSON("/background/load", {path: path}).then(function() {
      bgFileWrap.style.display = "none";
    }).catch(function() {});
  });

  // Colormap — sync with header toolbar select and server
  cmapSelect.addEventListener("change", function() {
    var name = cmapSelect.value;
    // Sync toolbar dropdown if it exists
    var toolbarCmap = document.getElementById("cmapSelect");
    if (toolbarCmap) toolbarCmap.value = name;
    // Push to server
    postJSON("/display/colormap", {name: name}).catch(function() {});
  });

  // Keep this select in sync when the toolbar one changes
  var toolbarCmap = document.getElementById("cmapSelect");
  if (toolbarCmap) {
    toolbarCmap.addEventListener("change", function() {
      cmapSelect.value = toolbarCmap.value;
    });
  }

  // Crosshair toggle (display only — no server endpoint for this yet)
  crosshairBtn.addEventListener("click", function() {
    crosshairBtn.classList.toggle("active");
  });

  // -----------------------------------------------------------------------
  // Initialisation — fetch initial state from server
  // -----------------------------------------------------------------------
  function init() {
    // Prefixes
    api("/config").then(function(r) { return r.json(); }).then(function(data) {
      clearChildren(prefixSelect);
      (data.available_prefixes || []).forEach(function(p) {
        var opt = document.createElement("option");
        opt.value = p;
        opt.textContent = p;
        prefixSelect.appendChild(opt);
      });
      if (data.active_prefix) prefixSelect.value = data.active_prefix;
    }).catch(function() {});

    // Streaming
    api("/streaming").then(function(r) { return r.json(); }).then(function(data) {
      if (data.streaming) {
        streamBtn.classList.add("active");
      } else {
        streamBtn.classList.remove("active");
      }
    }).catch(function() {});

    // Background
    api("/background").then(function(r) { return r.json(); }).then(function(data) {
      syncBackground(data);
    }).catch(function() {});

    // Analysis
    api("/analysis").then(function(r) { return r.json(); }).then(function(data) {
      if (data.fit_full_enabled !== undefined) {
        fitFullBtn.classList.toggle("active", !!data.fit_full_enabled);
      }
      if (data.fit_roi_enabled !== undefined) {
        fitRoiBtn.classList.toggle("active", !!data.fit_roi_enabled);
      }
    }).catch(function() {});

    // Colormap
    api("/display/colormap").then(function(r) { return r.json(); }).then(function(data) {
      if (data.current) cmapSelect.value = data.current;
    }).catch(function() {});
  }

  // -----------------------------------------------------------------------
  // WebSocket readback — call from the main WS message handler
  // -----------------------------------------------------------------------
  function syncBackground(data) {
    if (!data) return;
    var hasBg = !!data.has_background;
    bgSubBtn.disabled = !hasBg;
    saveBgBtn.disabled = !hasBg;
    bgStatus.textContent = hasBg ? "BG: acquired" : "BG: none";
    if (data.subtraction_enabled !== undefined) {
      bgSubBtn.classList.toggle("active", !!data.subtraction_enabled);
    }
  }

  function onWSMessage(msg) {
    // Keep controls in sync with server state delivered via WS
    if (msg.streaming !== undefined) {
      streamBtn.classList.toggle("active", !!msg.streaming);
    }
    if (msg.background) {
      syncBackground(msg.background);
    }
    if (msg.analysis) {
      if (msg.analysis.fit_full_enabled !== undefined) {
        fitFullBtn.classList.toggle("active", !!msg.analysis.fit_full_enabled);
      }
      if (msg.analysis.fit_roi_enabled !== undefined) {
        fitRoiBtn.classList.toggle("active", !!msg.analysis.fit_roi_enabled);
      }
    }
    if (msg.colormap) {
      cmapSelect.value = msg.colormap;
      var toolbarCmap = document.getElementById("cmapSelect");
      if (toolbarCmap) toolbarCmap.value = msg.colormap;
    }
  }

  // Kick off init
  init();

  return {
    onWSMessage: onWSMessage,
    init: init,
  };

})();
