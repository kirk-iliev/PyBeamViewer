"""Tests for API routes using FastAPI TestClient with a mocked bridge.

These tests verify that:
1. All routes return correct status codes
2. Request validation works (Pydantic)
3. Routes correctly delegate to the bridge
4. Error responses are properly formatted
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import numpy as np
import pytest
from fastapi.testclient import TestClient

from api.bridge import ApiBridge
from api.dependencies import get_bridge, init_bridge
from api.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def mock_bridge():
    """Create a fully-mocked ApiBridge for route testing."""
    bridge = MagicMock(spec=ApiBridge)

    # Camera
    bridge.get_camera_info.return_value = {
        "active_prefix": "TEST",
        "host": "127.0.0.1",
        "port": 15064,
        "image_pv": "TEST:image1:ArrayData",
        "width_pv": "TEST:image1:ArraySize0_RBV",
        "height_pv": "TEST:image1:ArraySize1_RBV",
        "exposure_pv": "TEST:cam1:AcquireTime",
        "exposure_rbv_pv": "TEST:cam1:AcquireTime_RBV",
        "gain_pv": "TEST:cam1:Gain",
        "gain_rbv_pv": "TEST:cam1:Gain_RBV",
        "fallback_shape": [300, 300],
    }

    # Streaming
    bridge.get_streaming_status.return_value = {
        "streaming": True,
        "connected": True,
        "frame_count": 100,
    }

    # Background
    bridge.get_background_status.return_value = {
        "has_background": False,
        "subtraction_enabled": False,
    }
    bridge.list_backgrounds.return_value = []

    # Analysis
    bridge.get_analysis_status.return_value = {
        "fit_full_enabled": True,
        "fit_roi_enabled": False,
        "x_fit": None,
        "y_fit": None,
    }

    # ROI
    bridge.get_roi.return_value = {"active": False, "roi": None}

    # Centroid / Drift
    bridge.get_drift.return_value = {
        "has_reference": False,
        "crosshair_enabled": False,
        "reference": None,
        "live": None,
    }

    # Display
    bridge.get_theme.return_value = "dark"
    bridge.get_colormap.return_value = "hot"

    # Overlays
    bridge.get_overlay_settings.return_value = {
        "h_enabled": False, "h_side": "bottom",
        "v_enabled": False, "v_side": "left",
        "scale": 0.25, "show_full": True, "show_roi": True,
    }

    # Trending
    bridge.get_trending_config.return_value = {"visible": False, "depth": 300}
    bridge.get_trending_history.return_value = {
        "count": 0,
        "frame_number": [], "sigma_x": [], "sigma_y": [],
        "centroid_x": [], "centroid_y": [],
        "roi_sigma_x": [], "roi_sigma_y": [],
        "drift_x": [], "drift_y": [],
    }

    # Frames
    bridge.get_frame_metadata.return_value = {
        "frame_number": 42,
        "fps": 10.0,
        "height": 200,
        "width": 300,
        "dtype": "uint16",
    }
    bridge.get_frame_png_b64.return_value = "iVBOR..."
    bridge.get_projections.return_value = {
        "x_projection": [1.0, 2.0, 3.0],
        "y_projection": [4.0, 5.0, 6.0],
    }
    bridge.get_roi_frame_data.return_value = {"active": False}

    # Config
    bridge.get_config_overview.return_value = {
        "active_prefix": "TEST",
        "available_prefixes": ["TEST", "OTHER"],
        "epics": {"host": "127.0.0.1", "port": 15064},
        "display": {"enable_fitting": True},
    }
    bridge.get_prefix_info.return_value = {
        "name": "TEST",
        "image_pv": "TEST:image1:ArrayData",
        "width_pv": "TEST:image1:ArraySize0_RBV",
        "height_pv": "TEST:image1:ArraySize1_RBV",
        "calibration": None,
    }
    bridge.get_calibration_info.return_value = {
        "is_calibrated": False,
        "um_per_pixel": 1.0,
        "unit_label": "px",
        "description": "No calibration",
    }

    return bridge


@pytest.fixture
def client(mock_bridge):
    """Create a TestClient with the mocked bridge injected."""
    app = create_app()
    app.dependency_overrides[get_bridge] = lambda: mock_bridge
    return TestClient(app)


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

class TestHealthEndpoint:
    def test_health(self, client, mock_bridge):
        resp = client.get("/health")
        assert resp.status_code == 200
        data = resp.json()
        assert data["status"] == "ok"


# ---------------------------------------------------------------------------
# Camera routes
# ---------------------------------------------------------------------------

class TestCameraRoutes:
    def test_get_camera(self, client):
        resp = client.get("/camera")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_prefix"] == "TEST"

    def test_set_prefix(self, client, mock_bridge):
        resp = client.post("/camera/prefix", json={"prefix": "OTHER"})
        assert resp.status_code == 200
        mock_bridge.select_prefix.assert_called_once_with("OTHER")

    def test_set_prefix_invalid(self, client, mock_bridge):
        mock_bridge.select_prefix.side_effect = ValueError("Unknown prefix")
        resp = client.post("/camera/prefix", json={"prefix": "NOPE"})
        assert resp.status_code == 400

    def test_set_exposure(self, client, mock_bridge):
        resp = client.post("/camera/exposure", json={"value": 0.5})
        assert resp.status_code == 200
        mock_bridge.set_exposure.assert_called_once_with(0.5)

    def test_set_exposure_invalid(self, client):
        resp = client.post("/camera/exposure", json={"value": -1.0})
        assert resp.status_code == 422  # validation error

    def test_set_gain(self, client, mock_bridge):
        resp = client.post("/camera/gain", json={"value": 10})
        assert resp.status_code == 200
        mock_bridge.set_gain.assert_called_once_with(10)

    def test_set_gain_invalid(self, client):
        resp = client.post("/camera/gain", json={"value": 50})
        assert resp.status_code == 422


# ---------------------------------------------------------------------------
# Streaming routes
# ---------------------------------------------------------------------------

class TestStreamingRoutes:
    def test_get_streaming(self, client):
        resp = client.get("/streaming")
        assert resp.status_code == 200
        assert resp.json()["streaming"] is True

    def test_set_streaming(self, client, mock_bridge):
        resp = client.post("/streaming", json={"streaming": False})
        assert resp.status_code == 200
        mock_bridge.set_streaming.assert_called_once_with(False)


# ---------------------------------------------------------------------------
# Background routes
# ---------------------------------------------------------------------------

class TestBackgroundRoutes:
    def test_get_background(self, client):
        resp = client.get("/background")
        assert resp.status_code == 200
        assert resp.json()["has_background"] is False

    def test_acquire_background(self, client, mock_bridge):
        resp = client.post("/background/acquire")
        assert resp.status_code == 200
        mock_bridge.acquire_background.assert_called_once()

    def test_set_subtraction_no_bg(self, client, mock_bridge):
        resp = client.post("/background/subtraction", json={"enabled": True})
        assert resp.status_code == 400  # no background to subtract

    def test_set_subtraction_with_bg(self, client, mock_bridge):
        mock_bridge.get_background_status.return_value = {
            "has_background": True,
            "subtraction_enabled": False,
        }
        resp = client.post("/background/subtraction", json={"enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_background_subtraction.assert_called_once_with(True)

    def test_save_background_no_bg(self, client, mock_bridge):
        resp = client.post("/background/save")
        assert resp.status_code == 400

    def test_save_background_with_bg(self, client, mock_bridge):
        mock_bridge.get_background_status.return_value = {
            "has_background": True,
            "subtraction_enabled": False,
        }
        resp = client.post("/background/save")
        assert resp.status_code == 200

    def test_load_background(self, client, mock_bridge):
        resp = client.post("/background/load", json={"path": "/tmp/bg.npy"})
        assert resp.status_code == 200
        mock_bridge.load_background.assert_called_once_with("/tmp/bg.npy")

    def test_list_backgrounds(self, client):
        resp = client.get("/background/list")
        assert resp.status_code == 200
        assert resp.json()["backgrounds"] == []


# ---------------------------------------------------------------------------
# Analysis routes
# ---------------------------------------------------------------------------

class TestAnalysisRoutes:
    def test_get_analysis(self, client):
        resp = client.get("/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert data["fit_full_enabled"] is True

    def test_set_fit_full(self, client, mock_bridge):
        resp = client.post("/analysis/fit-full", json={"enabled": False})
        assert resp.status_code == 200
        mock_bridge.set_fit_full.assert_called_once_with(False)

    def test_set_fit_roi(self, client, mock_bridge):
        resp = client.post("/analysis/fit-roi", json={"enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_fit_roi.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# ROI routes
# ---------------------------------------------------------------------------

class TestRoiRoutes:
    def test_get_roi_inactive(self, client):
        resp = client.get("/roi")
        assert resp.status_code == 200
        assert resp.json()["active"] is False

    def test_set_roi(self, client, mock_bridge):
        resp = client.post("/roi", json={"x0": 10, "y0": 20, "x1": 100, "y1": 200})
        assert resp.status_code == 200
        mock_bridge.set_roi.assert_called_once_with(10, 20, 100, 200)

    def test_set_roi_invalid(self, client):
        # x1 <= x0
        resp = client.post("/roi", json={"x0": 100, "y0": 20, "x1": 50, "y1": 200})
        assert resp.status_code == 400

    def test_clear_roi(self, client, mock_bridge):
        resp = client.delete("/roi")
        assert resp.status_code == 200
        mock_bridge.clear_roi.assert_called_once()

    def test_center_roi_no_active(self, client, mock_bridge):
        resp = client.post("/roi/center")
        assert resp.status_code == 400

    def test_center_roi_active(self, client, mock_bridge):
        mock_bridge.get_roi.return_value = {
            "active": True,
            "roi": {"x0": 10, "y0": 10, "x1": 100, "y1": 100},
        }
        resp = client.post("/roi/center")
        assert resp.status_code == 200
        mock_bridge.center_roi.assert_called_once()


# ---------------------------------------------------------------------------
# Centroid routes
# ---------------------------------------------------------------------------

class TestCentroidRoutes:
    def test_get_drift(self, client):
        resp = client.get("/centroid")
        assert resp.status_code == 200
        assert resp.json()["has_reference"] is False

    def test_set_crosshair(self, client, mock_bridge):
        resp = client.post("/centroid/crosshair", json={"enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_crosshair.assert_called_once_with(True)


# ---------------------------------------------------------------------------
# Display routes
# ---------------------------------------------------------------------------

class TestDisplayRoutes:
    def test_get_theme(self, client):
        resp = client.get("/display/theme")
        assert resp.status_code == 200
        assert resp.json()["theme"] == "dark"

    def test_toggle_theme(self, client, mock_bridge):
        resp = client.post("/display/theme/toggle")
        assert resp.status_code == 200
        mock_bridge.toggle_theme.assert_called_once()

    def test_get_colormap(self, client):
        resp = client.get("/display/colormap")
        assert resp.status_code == 200
        data = resp.json()
        assert data["current"] == "hot"
        assert "viridis" in data["available"]

    def test_set_colormap_valid(self, client, mock_bridge):
        resp = client.post("/display/colormap", json={"name": "inferno"})
        assert resp.status_code == 200
        mock_bridge.set_colormap.assert_called_once_with("inferno")

    def test_set_colormap_invalid(self, client, mock_bridge):
        mock_bridge.set_colormap.side_effect = ValueError("Invalid colormap")
        resp = client.post("/display/colormap", json={"name": "nope"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Overlay routes
# ---------------------------------------------------------------------------

class TestOverlayRoutes:
    def test_get_overlays(self, client):
        resp = client.get("/overlays")
        assert resp.status_code == 200
        assert resp.json()["scale"] == 0.25

    def test_set_overlays_partial(self, client, mock_bridge):
        resp = client.post("/overlays", json={"h_enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_overlay_settings.assert_called_once()

    def test_set_overlays_invalid_side(self, client):
        resp = client.post("/overlays", json={"h_side": "middle"})
        assert resp.status_code == 400


# ---------------------------------------------------------------------------
# Trending routes
# ---------------------------------------------------------------------------

class TestTrendingRoutes:
    def test_get_trending(self, client):
        resp = client.get("/trending")
        assert resp.status_code == 200
        assert resp.json()["visible"] is False

    def test_set_trending_visible(self, client, mock_bridge):
        resp = client.post("/trending/visible", json={"visible": True})
        assert resp.status_code == 200
        mock_bridge.set_trending_visible.assert_called_once_with(True)

    def test_set_trending_depth(self, client, mock_bridge):
        resp = client.post("/trending/depth", json={"depth": 500})
        assert resp.status_code == 200
        mock_bridge.set_trending_depth.assert_called_once_with(500)

    def test_set_trending_depth_invalid(self, client):
        resp = client.post("/trending/depth", json={"depth": 10})
        assert resp.status_code == 422

    def test_get_trending_history(self, client):
        resp = client.get("/trending/history")
        assert resp.status_code == 200
        assert resp.json()["count"] == 0


# ---------------------------------------------------------------------------
# Frame routes
# ---------------------------------------------------------------------------

class TestFrameRoutes:
    def test_get_frame_metadata(self, client):
        resp = client.get("/frames/metadata")
        assert resp.status_code == 200
        assert resp.json()["frame_number"] == 42

    def test_get_current_frame(self, client):
        resp = client.get("/frames/current")
        assert resp.status_code == 200
        assert "image_b64_png" in resp.json()

    def test_get_projections(self, client):
        resp = client.get("/frames/projections")
        assert resp.status_code == 200
        data = resp.json()
        assert data["x_projection"] == [1.0, 2.0, 3.0]

    def test_get_roi_frame(self, client):
        resp = client.get("/frames/roi")
        assert resp.status_code == 200
        assert resp.json()["active"] is False


# ---------------------------------------------------------------------------
# Config routes
# ---------------------------------------------------------------------------

class TestConfigRoutes:
    def test_get_config(self, client):
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_prefix"] == "TEST"
        assert "TEST" in data["available_prefixes"]

    def test_get_prefix_info(self, client):
        resp = client.get("/config/prefix/TEST")
        assert resp.status_code == 200
        assert resp.json()["name"] == "TEST"

    def test_get_prefix_info_invalid(self, client, mock_bridge):
        mock_bridge.get_prefix_info.side_effect = ValueError("Unknown prefix")
        resp = client.get("/config/prefix/NOPE")
        assert resp.status_code == 404

    def test_get_calibration(self, client):
        resp = client.get("/config/calibration")
        assert resp.status_code == 200
        assert resp.json()["is_calibrated"] is False
