"""Integration tests for the headless beam viewer MCP tools and REST endpoints.

Tests the full FastAPI application created via ``create_app()`` from
``beam_viewer.api.server``, with a mocked HeadlessBridge standing in for the
real EPICS-connected backend.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from beam_viewer.api.dependencies import get_bridge
from beam_viewer.api.headless_bridge import HeadlessBridge
from beam_viewer.api.server import create_app


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def mock_bridge():
    """Build a MagicMock that mimics HeadlessBridge return values."""
    bridge = MagicMock(spec=HeadlessBridge)

    # Streaming / health
    bridge.get_streaming_status.return_value = {
        "streaming": True,
        "connected": True,
        "frame_count": 42,
    }

    # Camera
    bridge.get_camera_info.return_value = {
        "active_prefix": "SIM",
        "host": "127.0.0.1",
        "port": 15064,
        "image_pv": "SIM:image1:ArrayData",
        "width_pv": "SIM:image1:ArraySize0_RBV",
        "height_pv": "SIM:image1:ArraySize1_RBV",
        "exposure_pv": "SIM:cam1:AcquireTime",
        "exposure_rbv_pv": "SIM:cam1:AcquireTime_RBV",
        "gain_pv": "SIM:cam1:Gain",
        "gain_rbv_pv": "SIM:cam1:Gain_RBV",
        "fallback_shape": [480, 640],
    }

    # Background
    bridge.get_background_status.return_value = {
        "has_background": True,
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

    # Centroid / drift
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
        "h_enabled": False,
        "h_side": "bottom",
        "v_enabled": False,
        "v_side": "left",
        "scale": 0.25,
        "show_full": True,
        "show_roi": True,
    }

    # Trending
    bridge.get_trending_config.return_value = {"visible": True, "depth": 300}
    bridge.get_trending_history.return_value = {
        "count": 0,
        "frame_number": [],
        "sigma_x": [],
        "sigma_y": [],
        "centroid_x": [],
        "centroid_y": [],
        "roi_sigma_x": [],
        "roi_sigma_y": [],
        "drift_x": [],
        "drift_y": [],
    }

    # Frames
    bridge.get_frame_metadata.return_value = {
        "frame_number": 10,
        "fps": 5.0,
        "height": 480,
        "width": 640,
        "dtype": "uint16",
    }
    bridge.get_frame_png_b64.return_value = "iVBORw0KGgoAAAANS..."
    bridge.get_projections.return_value = {
        "x_projection": [1.0, 2.0, 3.0],
        "y_projection": [4.0, 5.0],
    }
    bridge.get_roi_frame_data.return_value = {"active": False}

    # Config
    bridge.get_config_overview.return_value = {
        "active_prefix": "SIM",
        "available_prefixes": ["SIM"],
        "epics": {"host": "127.0.0.1", "port": 15064},
        "display": {"enable_fitting": True},
    }
    bridge.get_prefix_info.return_value = {
        "name": "SIM",
        "image_pv": "SIM:image1:ArrayData",
        "width_pv": "SIM:image1:ArraySize0_RBV",
        "height_pv": "SIM:image1:ArraySize1_RBV",
        "calibration": None,
    }
    bridge.get_calibration_info.return_value = {
        "is_calibrated": False,
        "um_per_pixel": 1.0,
        "unit_label": "px",
        "description": "No calibration",
    }

    return bridge


@pytest.fixture()
def client(mock_bridge):
    """Create a TestClient with the mock bridge injected via dependency override."""
    app = create_app(mock_bridge)
    # Override the dependency so every route gets our mock
    app.dependency_overrides[get_bridge] = lambda: mock_bridge
    return TestClient(app)


# =========================================================================
# 1. Health endpoint
# =========================================================================


class TestHealth:
    def test_health_returns_200(self, client):
        resp = client.get("/health")
        assert resp.status_code == 200

    def test_health_has_status_field(self, client):
        data = client.get("/health").json()
        assert "status" in data
        assert data["status"] in ("ok", "degraded")

    def test_health_ok_when_connected_and_streaming(self, client):
        data = client.get("/health").json()
        assert data["status"] == "ok"
        assert data["connected"] is True
        assert data["streaming"] is True

    def test_health_degraded_when_disconnected(self, client, mock_bridge):
        mock_bridge.get_streaming_status.return_value = {
            "streaming": False,
            "connected": False,
            "frame_count": 0,
        }
        data = client.get("/health").json()
        assert data["status"] == "degraded"
        assert "reason" in data


# =========================================================================
# 2. MCP tools — validate response schemas
# =========================================================================
#
# The MCP tools live in ``beam_viewer.tools`` and delegate to a bridge
# instance. We test them by importing the tool functions directly and
# injecting our mock via ``set_bridge``.
# =========================================================================


class TestMcpTools:
    """Exercise each of the 15 MCP tool functions and validate return shape."""

    @pytest.fixture(autouse=True)
    def _inject_bridge(self, mock_bridge):
        from beam_viewer.tools import set_bridge
        set_bridge(mock_bridge)
        self.bridge = mock_bridge

    # -- beam_capture --

    def test_beam_capture(self):
        from beam_viewer.tools import beam_capture
        result = beam_capture()
        assert "metadata" in result
        assert "image_b64_png" in result

    # -- beam_status --

    def test_beam_status(self):
        from beam_viewer.tools import beam_status
        result = beam_status()
        assert "streaming" in result
        assert "camera" in result
        assert "frame" in result

    # -- beam_set_camera --

    def test_beam_set_camera(self):
        from beam_viewer.tools import beam_set_camera
        result = beam_set_camera(prefix="SIM")
        assert result["status"] == "ok"
        assert result["prefix"] == "SIM"
        self.bridge.select_prefix.assert_called_once_with("SIM")

    # -- beam_set_exposure --

    def test_beam_set_exposure(self):
        from beam_viewer.tools import beam_set_exposure
        result = beam_set_exposure(value=0.1)
        assert result["status"] == "ok"
        assert result["exposure"] == 0.1
        self.bridge.set_exposure.assert_called_once_with(0.1)

    # -- beam_set_gain --

    def test_beam_set_gain(self):
        from beam_viewer.tools import beam_set_gain
        result = beam_set_gain(value=5)
        assert result["status"] == "ok"
        assert result["gain"] == 5
        self.bridge.set_gain.assert_called_once_with(5)

    # -- beam_analysis --

    def test_beam_analysis(self):
        from beam_viewer.tools import beam_analysis
        result = beam_analysis()
        assert "fit_full_enabled" in result

    # -- beam_roi_set --

    def test_beam_roi_set(self):
        from beam_viewer.tools import beam_roi_set
        result = beam_roi_set(x0=10, y0=20, x1=100, y1=200)
        assert result["status"] == "ok"
        roi = result["roi"]
        assert roi == {"x0": 10, "y0": 20, "x1": 100, "y1": 200}
        self.bridge.set_roi.assert_called_once_with(10, 20, 100, 200)

    # -- beam_roi_clear --

    def test_beam_roi_clear(self):
        from beam_viewer.tools import beam_roi_clear
        result = beam_roi_clear()
        assert result["status"] == "ok"
        self.bridge.clear_roi.assert_called_once()

    # -- beam_roi_center --

    def test_beam_roi_center(self):
        from beam_viewer.tools import beam_roi_center
        self.bridge.get_roi.return_value = {
            "active": True,
            "roi": {"x0": 10, "y0": 10, "x1": 110, "y1": 110},
        }
        result = beam_roi_center()
        assert result["status"] == "ok"
        assert "roi" in result
        self.bridge.center_roi.assert_called_once()

    # -- beam_background_acquire --

    def test_beam_background_acquire(self):
        from beam_viewer.tools import beam_background_acquire
        result = beam_background_acquire()
        assert result["status"] == "ok"
        assert "background" in result
        self.bridge.acquire_background.assert_called_once()

    # -- beam_background_toggle --

    def test_beam_background_toggle_on(self):
        from beam_viewer.tools import beam_background_toggle
        result = beam_background_toggle(enabled=True)
        assert result["status"] == "ok"
        assert result["subtraction_enabled"] is True
        self.bridge.set_background_subtraction.assert_called_once_with(True)

    def test_beam_background_toggle_off(self):
        from beam_viewer.tools import beam_background_toggle
        result = beam_background_toggle(enabled=False)
        assert result["subtraction_enabled"] is False

    # -- beam_trending --

    def test_beam_trending(self):
        from beam_viewer.tools import beam_trending
        result = beam_trending()
        assert "config" in result
        assert "history" in result

    # -- beam_calibration --

    def test_beam_calibration(self):
        from beam_viewer.tools import beam_calibration
        result = beam_calibration()
        assert "is_calibrated" in result
        assert "um_per_pixel" in result

    # -- beam_drift --

    def test_beam_drift(self):
        from beam_viewer.tools import beam_drift
        result = beam_drift()
        assert "has_reference" in result
        assert "crosshair_enabled" in result

    # -- beam_config (read) --

    def test_beam_config_read(self):
        from beam_viewer.tools import beam_config
        result = beam_config()
        assert "active_prefix" in result

    # -- beam_config (update) --

    def test_beam_config_update(self):
        from beam_viewer.tools import beam_config
        result = beam_config(updates={"exposure": 0.5})
        self.bridge.set_exposure.assert_called_once_with(0.5)
        assert "active_prefix" in result


# =========================================================================
# 3. REST endpoints — key route groups return valid JSON
# =========================================================================


class TestCameraEndpoints:
    def test_get_camera(self, client):
        resp = client.get("/camera")
        assert resp.status_code == 200
        data = resp.json()
        assert data["active_prefix"] == "SIM"
        assert "image_pv" in data

    def test_post_prefix(self, client, mock_bridge):
        resp = client.post("/camera/prefix", json={"prefix": "SIM"})
        assert resp.status_code == 200
        mock_bridge.select_prefix.assert_called_once_with("SIM")

    def test_post_exposure(self, client, mock_bridge):
        resp = client.post("/camera/exposure", json={"value": 0.05})
        assert resp.status_code == 200

    def test_post_gain(self, client, mock_bridge):
        resp = client.post("/camera/gain", json={"value": 3})
        assert resp.status_code == 200


class TestStreamingEndpoints:
    def test_get_streaming(self, client):
        resp = client.get("/streaming")
        assert resp.status_code == 200
        data = resp.json()
        assert "streaming" in data
        assert "connected" in data

    def test_post_streaming(self, client, mock_bridge):
        resp = client.post("/streaming", json={"streaming": False})
        assert resp.status_code == 200
        mock_bridge.set_streaming.assert_called_once_with(False)


class TestBackgroundEndpoints:
    def test_get_background(self, client):
        resp = client.get("/background")
        assert resp.status_code == 200
        data = resp.json()
        assert "has_background" in data

    def test_acquire_background(self, client, mock_bridge):
        resp = client.post("/background/acquire")
        assert resp.status_code == 200
        mock_bridge.acquire_background.assert_called_once()

    def test_subtraction_toggle(self, client, mock_bridge):
        resp = client.post("/background/subtraction", json={"enabled": True})
        assert resp.status_code == 200

    def test_list_backgrounds(self, client):
        resp = client.get("/background/list")
        assert resp.status_code == 200
        assert "backgrounds" in resp.json()


class TestAnalysisEndpoints:
    def test_get_analysis(self, client):
        resp = client.get("/analysis")
        assert resp.status_code == 200
        data = resp.json()
        assert "fit_full_enabled" in data

    def test_post_fit_full(self, client, mock_bridge):
        resp = client.post("/analysis/fit-full", json={"enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_fit_full.assert_called_once_with(True)

    def test_post_fit_roi(self, client, mock_bridge):
        resp = client.post("/analysis/fit-roi", json={"enabled": False})
        assert resp.status_code == 200


class TestRoiEndpoints:
    def test_get_roi(self, client):
        resp = client.get("/roi")
        assert resp.status_code == 200
        data = resp.json()
        assert "active" in data

    def test_set_roi(self, client, mock_bridge):
        resp = client.post("/roi", json={"x0": 5, "y0": 10, "x1": 50, "y1": 80})
        assert resp.status_code == 200
        mock_bridge.set_roi.assert_called_once_with(5, 10, 50, 80)

    def test_clear_roi(self, client, mock_bridge):
        resp = client.delete("/roi")
        assert resp.status_code == 200
        mock_bridge.clear_roi.assert_called_once()

    def test_center_roi_requires_active(self, client):
        resp = client.post("/roi/center")
        assert resp.status_code == 400


class TestTrendingEndpoints:
    def test_get_trending_config(self, client):
        resp = client.get("/trending")
        assert resp.status_code == 200
        data = resp.json()
        assert "depth" in data

    def test_get_trending_history(self, client):
        resp = client.get("/trending/history")
        assert resp.status_code == 200
        data = resp.json()
        assert "count" in data
        assert "sigma_x" in data

    def test_set_trending_depth(self, client, mock_bridge):
        resp = client.post("/trending/depth", json={"depth": 500})
        assert resp.status_code == 200
        mock_bridge.set_trending_depth.assert_called_once_with(500)


class TestConfigEndpoints:
    def test_get_config(self, client):
        resp = client.get("/config")
        assert resp.status_code == 200
        data = resp.json()
        assert "active_prefix" in data
        assert "available_prefixes" in data

    def test_get_prefix_info(self, client):
        resp = client.get("/config/prefix/SIM")
        assert resp.status_code == 200
        assert resp.json()["name"] == "SIM"

    def test_get_prefix_info_unknown(self, client, mock_bridge):
        mock_bridge.get_prefix_info.side_effect = ValueError("Unknown")
        resp = client.get("/config/prefix/NOPE")
        assert resp.status_code == 404

    def test_get_calibration(self, client):
        resp = client.get("/config/calibration")
        assert resp.status_code == 200
        data = resp.json()
        assert "is_calibrated" in data
        assert "um_per_pixel" in data


class TestDisplayEndpoints:
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
        assert "current" in data
        assert "available" in data

    def test_set_colormap(self, client, mock_bridge):
        resp = client.post("/display/colormap", json={"name": "viridis"})
        assert resp.status_code == 200
        mock_bridge.set_colormap.assert_called_once_with("viridis")


class TestOverlayEndpoints:
    def test_get_overlays(self, client):
        resp = client.get("/overlays")
        assert resp.status_code == 200
        data = resp.json()
        assert "h_enabled" in data
        assert "scale" in data

    def test_set_overlays(self, client, mock_bridge):
        resp = client.post("/overlays", json={"h_enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_overlay_settings.assert_called_once()

    def test_set_overlays_invalid_side(self, client):
        resp = client.post("/overlays", json={"h_side": "middle"})
        assert resp.status_code == 400


class TestCentroidEndpoints:
    def test_get_drift(self, client):
        resp = client.get("/centroid")
        assert resp.status_code == 200
        data = resp.json()
        assert "has_reference" in data
        assert "crosshair_enabled" in data

    def test_set_crosshair(self, client, mock_bridge):
        resp = client.post("/centroid/crosshair", json={"enabled": True})
        assert resp.status_code == 200
        mock_bridge.set_crosshair.assert_called_once_with(True)

    def test_set_centroid_reference(self, client, mock_bridge):
        resp = client.post("/centroid/reference", json={"x": 320.5, "y": 240.0})
        assert resp.status_code == 200
        mock_bridge.set_centroid_reference.assert_called_once_with(320.5, 240.0)

    def test_clear_centroid_reference(self, client, mock_bridge):
        resp = client.delete("/centroid/reference")
        assert resp.status_code == 200
        mock_bridge.clear_centroid_reference.assert_called_once()


class TestFrameEndpoints:
    def test_get_frame_metadata(self, client):
        resp = client.get("/frames/metadata")
        assert resp.status_code == 200
        data = resp.json()
        assert data["frame_number"] == 10
        assert data["width"] == 640

    def test_get_current_frame(self, client):
        resp = client.get("/frames/current")
        assert resp.status_code == 200
        data = resp.json()
        assert "image_b64_png" in data
        assert "metadata" in data

    def test_get_projections(self, client):
        resp = client.get("/frames/projections")
        assert resp.status_code == 200
        data = resp.json()
        assert "x_projection" in data
        assert "y_projection" in data

    def test_get_roi_frame(self, client):
        resp = client.get("/frames/roi")
        assert resp.status_code == 200
        assert "active" in resp.json()
