"""
epics_layer.py — EPICS / Channel Access communication layer.

Provides low-level caproto TCP helpers and a ``QThread``-based worker that
subscribes to image + dimension PVs and emits fully-reshaped frames as
``numpy`` arrays.  All network I/O lives on the worker thread; cross-thread
delivery happens via Qt signals (automatically queued).
"""

from __future__ import annotations

import socket
import select
import threading
import time
from typing import List, Optional, Tuple

import caproto as ca
import numpy as np
from PyQt6.QtCore import QThread, pyqtSignal


# ---------------------------------------------------------------------------
# Low-level caproto helpers
# ---------------------------------------------------------------------------

def drain(
    sock: socket.socket,
    circuit: ca.VirtualCircuit,
    timeout: float = 10.0,
    idle_timeout: float = 0.05,
) -> List:
    """Read from *sock* until quiet, returning processed CA commands.

    *idle_timeout* controls how long to wait for the next chunk after
    receiving at least one command.  Keeping it small (50 ms default)
    avoids a noticeable latency tax on every request-response cycle
    while still draining back-to-back packets reliably.
    """
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
            # We got an empty read, break out of main loop and close socket
            raise ConnectionError("Socket closed by peer")
        cmds, _ = circuit.recv(data)
        for c in cmds:
            circuit.process_command(c)
        commands.extend(cmds)
    return commands


def connect_epics(
    host: str,
    port: int,
    timeout: float = 10.0,
) -> Tuple[socket.socket, ca.VirtualCircuit]:
    """TCP connect + CA handshake.  Returns ``(socket, circuit)``."""
    sock = socket.create_connection((host, port), timeout=timeout)
    sock.setblocking(False)
    circuit = ca.VirtualCircuit(
        our_role=ca.CLIENT,
        address=(host, port),
        priority=0,
    )
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


def open_channel(
    sock: socket.socket,
    circuit: ca.VirtualCircuit,
    pv_name: str,
    timeout: float = 10.0,
) -> ca.ClientChannel:
    """Open a channel, raising on failure (use for mandatory PVs)."""
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


def open_channel_safe(
    sock: socket.socket,
    circuit: ca.VirtualCircuit,
    pv_name: str,
    timeout: float = 5.0,
) -> Optional[ca.ClientChannel]:
    """Try to open a channel.  Returns ``None`` on failure (optional PVs)."""
    try:
        cid = circuit.new_channel_id()
        chan = ca.ClientChannel(pv_name, circuit, cid=cid)
        for b in circuit.send(chan.create()):
            sock.sendall(bytes(b))
        deadline = time.monotonic() + timeout
        while chan.states[ca.CLIENT] is not ca.CONNECTED:
            if chan.states[ca.CLIENT] is ca.FAILED:
                print(f"  ✗ {pv_name!r} (PV does not exist or access denied)")
                return None
            if time.monotonic() > deadline:
                print(f"  ✗ {pv_name!r} timed out")
                return None
            drain(sock, circuit, timeout=0.1)
        print(f"  ✓ {pv_name!r}")
        return chan
    except Exception as exc:
        print(f"  ✗ {pv_name!r}: {exc}")
        return None


# ---------------------------------------------------------------------------
# One-shot get / put helpers (each creates a temporary TCP connection)
# ---------------------------------------------------------------------------

def epics_get(
    host: str,
    port: int,
    pv_name: str,
    timeout: float = 5.0,
):
    """One-shot channel-access read (*caget* equivalent).

    Creates a temporary TCP connection, reads the PV, and returns the data
    tuple.  Suitable for infrequent reads from any thread.
    """
    sock, circuit = connect_epics(host, port, timeout)
    try:
        chan = open_channel(sock, circuit, pv_name, timeout)
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


def epics_put(
    host: str,
    port: int,
    pv_name: str,
    value,
    timeout: float = 5.0,
) -> None:
    """One-shot channel-access write (*caput* equivalent).

    Creates a temporary TCP connection, writes the value, and waits for
    confirmation.  Suitable for infrequent writes from any thread.
    """
    sock, circuit = connect_epics(host, port, timeout)
    try:
        chan = open_channel(sock, circuit, pv_name, timeout)
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


# ---------------------------------------------------------------------------
# Producer thread
# ---------------------------------------------------------------------------

class EpicsWorker(QThread):
    """Background thread that subscribes to EPICS image + metadata PVs
    and emits fully-reshaped frames as numpy arrays.

    Signals
    -------
    new_frame : np.ndarray
        Emitted each time a complete image frame is received.
    connection_changed : bool
        ``True`` when the TCP circuit is established, ``False`` on disconnect.
    error_occurred : str
        Human-readable description of a recoverable error.
    """

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
        self.fallback_shape = fallback_shape  # (height, width) used when metadata PVs fail
        self.debug = debug

        self._stop_event = threading.Event()
        self._width: Optional[int] = None
        self._height: Optional[int] = None

    # -- public API ---------------------------------------------------------

    def stop(self) -> None:
        """Request the worker to stop and block until it finishes."""
        self._stop_event.set()
        self.wait()

    # -- thread entry point -------------------------------------------------

    def run(self) -> None:  # noqa: C901  (complexity inherited from protocol)
        _RETRY_DELAYS = (2.0, 5.0, 10.0, 30.0)  # seconds between reconnect attempts
        attempt = 0

        while not self._stop_event.is_set():
            sock: Optional[socket.socket] = None
            try:
                print(f"Connecting to {self.host}:{self.port} … (attempt {attempt + 1})")
                sock, circuit = connect_epics(self.host, self.port)
                attempt = 0  # reset on successful connection
                self.connection_changed.emit(True)

                # 1. Mandatory image channel
                print("Opening image channel …")
                ch_img = open_channel(sock, circuit, self.image_pv)
                img_sub_req = ch_img.subscribe(mask=ca.SubscriptionType.DBE_VALUE)
                img_sub_id = img_sub_req.subscriptionid
                print(f"  -> image subscription id: {img_sub_id}")
                for b in circuit.send(img_sub_req):
                    sock.sendall(bytes(b))

                # 2. Optional metadata channels
                print("Attempting metadata channels …")
                ch_width = open_channel_safe(sock, circuit, self.width_pv, timeout=2)
                ch_height = open_channel_safe(sock, circuit, self.height_pv, timeout=2)

                use_metadata = ch_width is not None and ch_height is not None
                width_sub_id: Optional[int] = None
                height_sub_id: Optional[int] = None

                if use_metadata:
                    print("Using live metadata for dimensions.")
                    w_req = ch_width.subscribe()
                    width_sub_id = w_req.subscriptionid
                    for b in circuit.send(w_req):
                        sock.sendall(bytes(b))

                    h_req = ch_height.subscribe()
                    height_sub_id = h_req.subscriptionid
                    for b in circuit.send(h_req):
                        sock.sendall(bytes(b))
                else:
                    if self.fallback_shape is not None:
                        h, w = self.fallback_shape
                        print(f"Metadata unavailable — using fallback shape {h}×{w}.")
                    else:
                        print("Metadata unavailable — falling back to square guessing.")

                # 3. Event loop
                while not self._stop_event.is_set():
                    for cmd in drain(sock, circuit, timeout=0.05):
                        # Helpful debug output to diagnose why array data isn't arriving
                        if self.debug:
                            subid = getattr(cmd, "subscriptionid", None)
                            data_info = "N/A"
                            try:
                                if hasattr(cmd, "data"):
                                    data_info = f"len={len(cmd.data)} type={type(cmd.data).__name__}"
                            except Exception:
                                data_info = "<unreadable>"
                            print(f"DBG CMD: {type(cmd).__name__} subid={subid} {data_info}")

                        if not isinstance(cmd, ca.EventAddResponse):
                            print(f"Received unexpected command: {cmd!r}")
                            continue

                        # — dimension metadata updates —
                        if use_metadata:
                            if cmd.subscriptionid == width_sub_id:
                                self._width = int(cmd.data[0])
                                continue
                            if cmd.subscriptionid == height_sub_id:
                                self._height = int(cmd.data[0])
                                continue

                        # — image data —
                        if cmd.subscriptionid == img_sub_id:
                            # better to use np.frombuffer here if we know data type (likely uint16)
                            # np.frombuffer is faster but it can't guess the dtype
                            raw = np.asarray(cmd.data)
                            frame = self._reshape(raw, use_metadata)
                            if frame is not None:
                                self.new_frame.emit(frame)
                                # print(f"Emitted new frame of shape {frame.shape}")

            except Exception as exc:
                msg = f"EPICS worker error: {exc}"
                print(msg)
                self.error_occurred.emit(msg)
            finally:
                self.connection_changed.emit(False)
                if sock is not None:
                    print("Closing socket.")
                    sock.close()

            if self._stop_event.is_set():
                break

            delay = _RETRY_DELAYS[min(attempt, len(_RETRY_DELAYS) - 1)]
            attempt += 1
            print(f"Reconnecting in {delay:.0f} s …")
            self._stop_event.wait(delay)

    # -- internal helpers ---------------------------------------------------

    def _reshape(
        self,
        raw: np.ndarray,
        use_metadata: bool,
    ) -> Optional[np.ndarray]:
        """Reshape a flat pixel array into a 2-D frame, or return ``None``."""
        if use_metadata:
            if self._width is None or self._height is None:
                return None
            expected = self._width * self._height
            if raw.size >= expected:
                return raw[:expected].reshape((self._height, self._width))
            return None
        else:
            if self.fallback_shape is not None:
                h, w = self.fallback_shape
                expected = h * w
                if raw.size >= expected:
                    return raw[:expected].reshape((h, w))
                print(
                    f"[EpicsWorker] Frame size {raw.size} < fallback "
                    f"{h}×{w} ({expected}); dropping frame."
                )
                return None
            # Last resort: guess a square frame
            n = raw.size
            side = int(n ** 0.5)
            if side * side == n:
                return raw[:n].reshape((side, side))
            print(f"[EpicsWorker] Cannot reshape {n} pixels — not square and no fallback configured.")
            return None
