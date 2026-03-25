"""
epics_layer.py — EPICS / Channel Access communication layer.

Hybrid implementation:
1. Native Mode (Control Room): Uses the robust caproto.threading.client.Context
   with standard UDP discovery.
2. Tunnel Mode (SSH): Uses low-level sockets to bypass the CA Search phase,
   forcing all traffic to stay inside the TCP tunnel.
"""

from __future__ import annotations

import logging
import os
import select
import socket
import threading
import time
from typing import Any, List, Optional, Tuple

log = logging.getLogger(__name__)

import caproto as ca
import numpy as np
from PyQt5.QtCore import QThread, pyqtSignal
from caproto.threading.client import Context


# ---------------------------------------------------------------------------
# Low-level socket helpers (Strictly for SSH Tunnel mode)
# ---------------------------------------------------------------------------

def drain(
    sock: socket.socket,
    circuit: ca.VirtualCircuit,
    timeout: float = 10.0,
    idle_timeout: float = 0.05,
) -> List:
    commands: list = []
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        remaining = max(0.0, deadline - time.monotonic())
        wait = idle_timeout if commands else min(remaining, 0.5)
        ready = select.select([sock], [], [], wait)
        if not ready[0]:
            break
        data = sock.recv(65536)
        if not data:
            raise ConnectionError("Socket closed by peer")
        cmds, _ = circuit.recv(data)
        for c in cmds:
            circuit.process_command(c)
        commands.extend(cmds)
    return commands


def connect_epics_socket(
    host: str,
    port: int,
    timeout: float = 10.0,
) -> Tuple[socket.socket, ca.VirtualCircuit]:
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setblocking(False)
    circuit = ca.VirtualCircuit(our_role=ca.CLIENT, address=(host, port), priority=0)
    for msg in [
        ca.VersionRequest(version=13, priority=0),
        ca.HostNameRequest("localhost"),
        ca.ClientNameRequest("user"),
    ]:
        sock.sendall(b"".join(bytes(b) for b in circuit.send(msg)))

    if not select.select([sock], [], [], timeout)[0]:
        raise TimeoutError("No CA handshake response")
    data = sock.recv(4096)
    cmds, _ = circuit.recv(data)
    for c in cmds:
        circuit.process_command(c)
    return sock, circuit


def open_channel_socket(
    sock: socket.socket,
    circuit: ca.VirtualCircuit,
    pv_name: str,
    timeout: float = 10.0,
) -> ca.ClientChannel:
    cid = circuit.new_channel_id()
    chan = ca.ClientChannel(pv_name, circuit, cid=cid)
    for b in circuit.send(chan.create()):
        sock.sendall(bytes(b))
    deadline = time.monotonic() + timeout
    while chan.states[ca.CLIENT] is not ca.CONNECTED:
        if time.monotonic() > deadline:
            raise TimeoutError(f"Channel {pv_name!r} did not connect")
        drain(sock, circuit, timeout=0.5)
    return chan


def open_channel_safe_socket(
    sock: socket.socket,
    circuit: ca.VirtualCircuit,
    pv_name: str,
    timeout: float = 5.0,
) -> Optional[ca.ClientChannel]:
    try:
        cid = circuit.new_channel_id()
        chan = ca.ClientChannel(pv_name, circuit, cid=cid)
        for b in circuit.send(chan.create()):
            sock.sendall(bytes(b))
        deadline = time.monotonic() + timeout
        while chan.states[ca.CLIENT] is not ca.CONNECTED:
            if chan.states[ca.CLIENT] is ca.FAILED:
                return None
            if time.monotonic() > deadline:
                return None
            drain(sock, circuit, timeout=0.1)
        return chan
    except Exception:
        return None


# ---------------------------------------------------------------------------
# Shared native-mode Context (created once, reused for all one-shot calls)
# ---------------------------------------------------------------------------

_native_ctx: Optional[Context] = None
_native_ctx_lock = threading.Lock()


def _get_native_ctx() -> Context:
    """Return the module-level singleton Context, creating it on first call."""
    global _native_ctx
    if _native_ctx is None:
        with _native_ctx_lock:
            if _native_ctx is None:          # double-checked locking
                _native_ctx = Context()
    return _native_ctx


def shutdown_native_ctx() -> None:
    """Disconnect the shared Context on application exit."""
    global _native_ctx
    with _native_ctx_lock:
        if _native_ctx is not None:
            try:
                _native_ctx.disconnect()
            except Exception:
                pass
            _native_ctx = None


# ---------------------------------------------------------------------------
# One-shot API
# ---------------------------------------------------------------------------

def epics_get(host: str, port: int, pv_name: str, timeout: float = 5.0):
    if host:
        # Tunnel Mode
        sock, circuit = connect_epics_socket(host, port, timeout)
        try:
            chan = open_channel_socket(sock, circuit, pv_name, timeout)
            req = chan.read()
            for b in circuit.send(req):
                sock.sendall(bytes(b))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for cmd in drain(sock, circuit, timeout=0.5):
                    if isinstance(cmd, ca.ReadNotifyResponse):
                        return cmd.data
            raise TimeoutError(f"No read response for {pv_name!r}")
        finally:
            sock.close()
    else:
        # Native Mode — reuse the shared long-lived Context
        ctx = _get_native_ctx()
        pv, = ctx.get_pvs(pv_name)
        pv.wait_for_connection(timeout=timeout)
        response = pv.read(timeout=timeout)
        return response.data


def epics_put(host: str, port: int, pv_name: str, value, timeout: float = 5.0) -> None:
    if host:
        # Tunnel Mode
        sock, circuit = connect_epics_socket(host, port, timeout)
        try:
            chan = open_channel_socket(sock, circuit, pv_name, timeout)
            if not isinstance(value, (list, tuple)):
                value = (value,)
            req = chan.write(data=value, notify=True)
            for b in circuit.send(req):
                sock.sendall(bytes(b))
            deadline = time.monotonic() + timeout
            while time.monotonic() < deadline:
                for cmd in drain(sock, circuit, timeout=0.5):
                    if isinstance(cmd, ca.WriteNotifyResponse):
                        return
            raise TimeoutError(f"No write-notify response for {pv_name!r}")
        finally:
            sock.close()
    else:
        # Native Mode — reuse the shared long-lived Context
        ctx = _get_native_ctx()
        pv, = ctx.get_pvs(pv_name)
        pv.wait_for_connection(timeout=timeout)
        pv.write(value, wait=True, timeout=timeout)


# ---------------------------------------------------------------------------
# Producer thread
# ---------------------------------------------------------------------------

class EpicsWorker(QThread):
    new_frame = pyqtSignal(np.ndarray)
    connection_changed = pyqtSignal(bool)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        host: str,
        port: int,
        image_pv: str,
        width_pv: str,
        height_pv: str,
        fallback_shape: Optional[Tuple[int, int]] = None,
        debug: bool = False,
    ) -> None:
        super().__init__()
        self.host = host
        self.port = port
        self.image_pv = image_pv
        self.width_pv = width_pv
        self.height_pv = height_pv
        self.fallback_shape = fallback_shape
        self.debug = debug

        self._stop_event = threading.Event()
        self._width: Optional[int] = None
        self._height: Optional[int] = None

    def stop(self) -> None:
        self._stop_event.set()
        if not self.wait(5000):
            log.warning("EpicsWorker did not finish within 5 s.")

    def request_stop(self) -> None:
        """Signal the worker to stop without blocking for completion."""
        self._stop_event.set()

    def run(self) -> None:
        if self.host:
            self._run_tunnel_mode()
        else:
            self._run_native_mode()

    # --- NATIVE MODE (Control Room) ---
    def _run_native_mode(self) -> None:
        _RETRY_DELAYS = (2.0, 5.0, 10.0, 30.0)
        attempt = 0

        while not self._stop_event.is_set():
            ctx = Context()
            subs: list[Any] = []

            try:
                pv_names = [self.image_pv]
                if self.width_pv: pv_names.append(self.width_pv)
                if self.height_pv: pv_names.append(self.height_pv)

                pvs = ctx.get_pvs(*pv_names)
                pv_map = {pv.name: pv for pv in pvs}
                img_pv = pv_map[self.image_pv]

                log.info("[Native Mode] Waiting for connection to %s ...", self.image_pv)
                while not self._stop_event.is_set():
                    try:
                        img_pv.wait_for_connection(timeout=1.0)
                        break
                    except ca.CaprotoTimeoutError:
                        continue

                if self._stop_event.is_set():
                    return

                attempt = 0
                self.connection_changed.emit(True)

                if self.width_pv and self.width_pv in pv_map:
                    def on_width(sub, response):
                        if self._stop_event.is_set(): return
                        if response.data is not None: self._width = int(response.data[0])
                    sub = pv_map[self.width_pv].subscribe()
                    sub.add_callback(on_width)
                    subs.append(sub)

                if self.height_pv and self.height_pv in pv_map:
                    def on_height(sub, response):
                        if self._stop_event.is_set(): return
                        if response.data is not None: self._height = int(response.data[0])
                    sub = pv_map[self.height_pv].subscribe()
                    sub.add_callback(on_height)
                    subs.append(sub)

                def on_image(sub, response):
                    if self._stop_event.is_set(): return
                    if response.data is not None:
                        raw = np.asarray(response.data)
                        frame = self._reshape(raw)
                        if frame is not None:
                            self.new_frame.emit(frame)

                img_sub = img_pv.subscribe()
                img_sub.add_callback(on_image)
                subs.append(img_sub)

                while not self._stop_event.is_set():
                    self._stop_event.wait(0.1)

            except Exception as exc:
                self.error_occurred.emit(str(exc))
            finally:
                self.connection_changed.emit(False)
                try:
                    ctx.disconnect()
                except Exception:
                    pass

            if self._stop_event.is_set():
                break
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            attempt += 1
            log.info("[Native Mode] Reconnecting in %.1f s (attempt %d)...", delay, attempt)
            self._stop_event.wait(delay)

    # --- TUNNEL MODE (SSH) ---
    def _run_tunnel_mode(self) -> None:
        _RETRY_DELAYS = (2.0, 5.0, 10.0, 30.0)
        attempt = 0

        while not self._stop_event.is_set():
            sock: Optional[socket.socket] = None
            try:
                log.info("[Tunnel Mode] Connecting to %s:%d ...", self.host, self.port)
                sock, circuit = connect_epics_socket(self.host, self.port)
                attempt = 0
                self.connection_changed.emit(True)

                ch_img = open_channel_socket(sock, circuit, self.image_pv)
                img_sub_req = ch_img.subscribe(mask=ca.SubscriptionType.DBE_VALUE)
                img_sub_id = img_sub_req.subscriptionid
                for b in circuit.send(img_sub_req): sock.sendall(bytes(b))

                ch_width = open_channel_safe_socket(sock, circuit, self.width_pv, timeout=2) if self.width_pv else None
                ch_height = open_channel_safe_socket(sock, circuit, self.height_pv, timeout=2) if self.height_pv else None

                width_sub_id, height_sub_id = None, None

                if ch_width and ch_height:
                    w_req = ch_width.subscribe()
                    width_sub_id = w_req.subscriptionid
                    for b in circuit.send(w_req): sock.sendall(bytes(b))

                    h_req = ch_height.subscribe()
                    height_sub_id = h_req.subscriptionid
                    for b in circuit.send(h_req): sock.sendall(bytes(b))

                while not self._stop_event.is_set():
                    for cmd in drain(sock, circuit, timeout=0.05):
                        if not isinstance(cmd, ca.EventAddResponse):
                            continue

                        if cmd.subscriptionid == width_sub_id:
                            self._width = int(cmd.data[0])
                        elif cmd.subscriptionid == height_sub_id:
                            self._height = int(cmd.data[0])
                        elif cmd.subscriptionid == img_sub_id:
                            raw = np.asarray(cmd.data)
                            frame = self._reshape(raw)
                            if frame is not None:
                                self.new_frame.emit(frame)

            except Exception as exc:
                self.error_occurred.emit(str(exc))
            finally:
                self.connection_changed.emit(False)
                if sock is not None: sock.close()

            if self._stop_event.is_set(): break
            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            attempt += 1
            self._stop_event.wait(delay)

    # --- COMMON ---
    def _reshape(self, raw: np.ndarray) -> Optional[np.ndarray]:
        if self._width is not None and self._height is not None:
            expected = self._width * self._height
            if raw.size >= expected:
                return raw[:expected].reshape((self._height, self._width))
            log.warning(
                "Frame has %d pixels but expected %d (%dx%d) — trying fallback.",
                raw.size, expected, self._width, self._height,
            )

        if self.fallback_shape is not None:
            h, w = self.fallback_shape
            expected = h * w
            if raw.size >= expected:
                return raw[:expected].reshape((h, w))
            log.warning(
                "Frame has %d pixels, cannot reshape to fallback %s.",
                raw.size, self.fallback_shape,
            )
            return None

        n = raw.size
        side = int(n ** 0.5)
        if side * side == n:
            return raw[:n].reshape((side, side))

        log.warning("Cannot reshape %d-pixel frame (no dimensions available).", raw.size)
        return None