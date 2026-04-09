"""
Tests for JPEG frame encoding in headless_bridge.py.
"""

from __future__ import annotations

import base64
import io
import time
from unittest.mock import MagicMock

import numpy as np
import pytest
from PIL import Image

from mcp_servers.beam_viewer.api.headless_bridge import (
    HeadlessBridge,
    _frame_to_jpeg_b64,
    _frame_to_png_b64,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def sample_frame_uint8():
    """A 100x100 gradient frame, uint8."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 256, size=(100, 100), dtype=np.uint8)


@pytest.fixture
def sample_frame_uint16():
    """A 100x100 gradient frame, uint16 (simulates 12/16-bit camera)."""
    rng = np.random.default_rng(42)
    return rng.integers(0, 65536, size=(100, 100), dtype=np.uint16)


@pytest.fixture
def large_frame():
    """Realistic beam image size (1038x1300), uint16."""
    rng = np.random.default_rng(0)
    return rng.integers(0, 65536, size=(1038, 1300), dtype=np.uint16)


@pytest.fixture
def bridge_with_frame():
    """HeadlessBridge wired to a mock state containing a sample frame."""
    state = MagicMock()
    ctrl = MagicMock()

    mock_fs = MagicMock()
    mock_fs.frame = np.arange(10000).reshape(100, 100).astype(np.uint16)
    mock_fs.frame_number = 1
    mock_fs.analysis = None
    state.frame_state = mock_fs
    state.connected = True
    state.frame_count = 1

    ctrl.streaming = True
    ctrl.fit_full = False
    ctrl.current_roi = None
    ctrl.centroid_reference = None
    ctrl.live_roi_centroid = None
    ctrl.crosshair_enabled = False
    ctrl.overlay_settings = {}

    mock_cal = MagicMock()
    mock_cal.is_calibrated = False
    ctrl.calibration = mock_cal

    bridge = HeadlessBridge(state, ctrl)
    bridge._start_time = time.time() - 1.0
    return bridge


# ---------------------------------------------------------------------------
# _frame_to_jpeg_b64 — basic encoding
# ---------------------------------------------------------------------------

class TestJpegEncoding:

    def test_produces_valid_jpeg(self, sample_frame_uint8):
        b64 = _frame_to_jpeg_b64(sample_frame_uint8)
        raw = base64.b64decode(b64)
        # JPEG magic bytes: FF D8 FF
        assert raw[:2] == b"\xff\xd8"
        # Verify PIL can open it
        img = Image.open(io.BytesIO(raw))
        assert img.format == "JPEG"
        assert img.size == (100, 100)

    def test_output_is_base64_string(self, sample_frame_uint8):
        b64 = _frame_to_jpeg_b64(sample_frame_uint8)
        assert isinstance(b64, str)
        # Should not raise
        base64.b64decode(b64)


# ---------------------------------------------------------------------------
# JPEG vs PNG size
# ---------------------------------------------------------------------------

class TestJpegSmallerThanPng:

    def test_jpeg_smaller_than_png(self, large_frame):
        jpeg_b64 = _frame_to_jpeg_b64(large_frame)
        png_b64 = _frame_to_png_b64(large_frame)
        jpeg_bytes = len(base64.b64decode(jpeg_b64))
        png_bytes = len(base64.b64decode(png_b64))
        assert jpeg_bytes < png_bytes, (
            f"JPEG ({jpeg_bytes} B) should be smaller than PNG ({png_bytes} B)"
        )


# ---------------------------------------------------------------------------
# Quality parameter
# ---------------------------------------------------------------------------

class TestQualityParameter:

    def test_lower_quality_yields_smaller_output(self, sample_frame_uint8):
        high = _frame_to_jpeg_b64(sample_frame_uint8, quality=95)
        low = _frame_to_jpeg_b64(sample_frame_uint8, quality=10)
        assert len(base64.b64decode(low)) < len(base64.b64decode(high))

    def test_default_quality_is_80(self, sample_frame_uint8):
        default = _frame_to_jpeg_b64(sample_frame_uint8)
        explicit_80 = _frame_to_jpeg_b64(sample_frame_uint8, quality=80)
        assert len(default) == len(explicit_80)


# ---------------------------------------------------------------------------
# uint16 input handling
# ---------------------------------------------------------------------------

class TestUint16Input:

    def test_uint16_produces_valid_jpeg(self, sample_frame_uint16):
        b64 = _frame_to_jpeg_b64(sample_frame_uint16)
        raw = base64.b64decode(b64)
        assert raw[:2] == b"\xff\xd8"
        img = Image.open(io.BytesIO(raw))
        assert img.mode == "L"

    def test_uint16_normalizes_to_full_range(self):
        """Ensure uint16 values are scaled into 0-255."""
        frame = np.array([[0, 65535]], dtype=np.uint16)
        b64 = _frame_to_jpeg_b64(frame)
        img = Image.open(io.BytesIO(base64.b64decode(b64)))
        pixels = np.array(img)
        # After normalization min should map near 0, max near 255
        # (JPEG is lossy, so allow some tolerance)
        assert pixels.min() < 10
        assert pixels.max() > 245

    def test_uniform_uint16_frame(self):
        """Constant-value uint16 frame should not crash."""
        frame = np.full((10, 10), 30000, dtype=np.uint16)
        b64 = _frame_to_jpeg_b64(frame)
        assert len(b64) > 0


# ---------------------------------------------------------------------------
# build_ws_frame_payload uses JPEG
# ---------------------------------------------------------------------------

class TestWsPayloadUsesJpeg:

    def test_payload_contains_jpeg_key(self, bridge_with_frame):
        payload = bridge_with_frame.build_ws_frame_payload()
        assert payload is not None
        assert "frame_jpeg_b64" in payload
        assert "frame_png_b64" not in payload

    def test_payload_jpeg_is_valid(self, bridge_with_frame):
        payload = bridge_with_frame.build_ws_frame_payload()
        raw = base64.b64decode(payload["frame_jpeg_b64"])
        assert raw[:2] == b"\xff\xd8"
