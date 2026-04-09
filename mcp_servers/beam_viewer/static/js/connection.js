"use strict";

/**
 * WebSocket connection manager with exponential backoff reconnection.
 *
 * States: disconnected -> connecting -> connected -> (close) -> reconnecting
 *
 * Exposes:
 *   Connection.start()           -- initiate connection
 *   Connection.onFrame(callback) -- register frame handler
 *   Connection.state()           -- "connected" | "disconnected" | "reconnecting"
 */

var Connection = (function() {
  var INITIAL_DELAY = 1000;   // 1 s
  var MAX_DELAY     = 16000;  // 16 s
  var BACKOFF_MULT  = 2;

  var ws = null;
  var reconnectTimer = null;
  var currentDelay = INITIAL_DELAY;
  var _state = "disconnected";
  var _onFrame = null;
  var _onStateChange = null;

  function setState(s) {
    _state = s;
    if (_onStateChange) _onStateChange(s);
  }

  function connect() {
    if (ws && (ws.readyState === WebSocket.CONNECTING || ws.readyState === WebSocket.OPEN)) {
      return;
    }
    setState("reconnecting");

    var proto = location.protocol === "https:" ? "wss:" : "ws:";
    var url   = proto + "//" + location.host + "/frames/ws/stream";
    ws = new WebSocket(url);

    ws.onopen = function() {
      setState("connected");
      currentDelay = INITIAL_DELAY;
      if (reconnectTimer) {
        clearTimeout(reconnectTimer);
        reconnectTimer = null;
      }
    };

    ws.onmessage = function(evt) {
      var msg;
      try { msg = JSON.parse(evt.data); } catch(e) { return; }
      if (msg.type === "frame" && _onFrame) {
        _onFrame(msg);
      }
    };

    ws.onclose = function() {
      setState("disconnected");
      scheduleReconnect();
    };

    ws.onerror = function() {
      // onclose fires after onerror -- handled there
    };
  }

  function scheduleReconnect() {
    if (reconnectTimer) return;
    setState("reconnecting");
    reconnectTimer = setTimeout(function() {
      reconnectTimer = null;
      currentDelay = Math.min(currentDelay * BACKOFF_MULT, MAX_DELAY);
      connect();
    }, currentDelay);
  }

  return {
    start: connect,
    state: function() { return _state; },
    onFrame: function(cb) { _onFrame = cb; },
    onStateChange: function(cb) { _onStateChange = cb; },
  };
})();
