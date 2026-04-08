"""Tests for API Pydantic schemas — validation, serialization, edge cases."""

from __future__ import annotations

import math

import pytest
from pydantic import ValidationError

from api.schemas.camera import CameraInfo, ExposureSet, GainSet, PrefixSelect
from api.schemas.common import AckResponse, ErrorResponse
from api.schemas.streaming import StreamingSet, StreamingStatus
from api.schemas.background import (
    BackgroundList,
    BackgroundLoadRequest,
    BackgroundStatus,
    BackgroundSubtractionSet,
    SavedBackground,
)
from api.schemas.analysis import AnalysisStatus, FitFullSet, FitResultSchema, FitRoiSet
from api.schemas.roi import RoiSpec, RoiState
from api.schemas.centroid import CentroidReference, CrosshairSet, DriftData
from api.schemas.display import ColormapSet, ThemeInfo
from api.schemas.overlays import OverlaySettings
from api.schemas.overlays import OverlayState as OverlayStateSchema
from api.schemas.trending import TrendingConfig, TrendingDepthSet, TrendingHistory, TrendingVisibleSet
from api.schemas.frames import FrameData, FrameMetadata, ProjectionData, RoiFrameData
from api.schemas.config_schemas import CalibrationInfo, ConfigOverview, PrefixInfo


class TestCommonSchemas:
    def test_ack_response_defaults(self):
        r = AckResponse()
        assert r.ok is True
        assert r.message == ""

    def test_ack_response_with_message(self):
        r = AckResponse(ok=True, message="done")
        assert r.message == "done"

    def test_error_response(self):
        r = ErrorResponse(error="bad", detail="something went wrong")
        assert r.error == "bad"
        assert r.detail == "something went wrong"


class TestCameraSchemas:
    def test_exposure_set_valid(self):
        e = ExposureSet(value=0.5)
        assert e.value == 0.5

    def test_exposure_set_too_low(self):
        with pytest.raises(ValidationError):
            ExposureSet(value=0.0)

    def test_exposure_set_too_high(self):
        with pytest.raises(ValidationError):
            ExposureSet(value=31.0)

    def test_gain_set_valid(self):
        g = GainSet(value=10)
        assert g.value == 10

    def test_gain_set_too_low(self):
        with pytest.raises(ValidationError):
            GainSet(value=-1)

    def test_gain_set_too_high(self):
        with pytest.raises(ValidationError):
            GainSet(value=41)

    def test_prefix_select(self):
        p = PrefixSelect(prefix="BL72")
        assert p.prefix == "BL72"

    def test_camera_info_roundtrip(self):
        info = CameraInfo(
            active_prefix="BL31",
            host="127.0.0.1",
            port=15064,
            image_pv="BL31:image1:ArrayData",
            width_pv="BL31:image1:ArraySize0_RBV",
            height_pv="BL31:image1:ArraySize1_RBV",
            exposure_pv="BL31:cam1:AcquireTime",
            exposure_rbv_pv="BL31:cam1:AcquireTime_RBV",
            gain_pv="BL31:cam1:Gain",
            gain_rbv_pv="BL31:cam1:Gain_RBV",
            fallback_shape=[300, 300],
        )
        d = info.model_dump()
        assert d["active_prefix"] == "BL31"
        assert d["fallback_shape"] == [300, 300]


class TestStreamingSchemas:
    def test_streaming_status(self):
        s = StreamingStatus(streaming=True, connected=True, frame_count=42)
        assert s.streaming is True
        assert s.frame_count == 42

    def test_streaming_set(self):
        s = StreamingSet(streaming=False)
        assert s.streaming is False


class TestBackgroundSchemas:
    def test_background_status(self):
        s = BackgroundStatus(has_background=True, subtraction_enabled=False)
        assert s.has_background is True

    def test_background_list(self):
        bl = BackgroundList(backgrounds=[
            SavedBackground(filename="bg1.npy", path="/tmp/bg1.npy"),
        ])
        assert len(bl.backgrounds) == 1


class TestAnalysisSchemas:
    def test_fit_result_schema(self):
        fr = FitResultSchema(
            success=True,
            sigma=12.5,
            sigma_um=23.6,
            centroid=100.0,
            centroid_um=188.52,
            amplitude=5000.0,
            offset=100.0,
            residual=0.5,
            unit_label="µm",
        )
        assert fr.success is True
        assert fr.sigma == 12.5

    def test_fit_result_schema_failed(self):
        fr = FitResultSchema(success=False)
        assert fr.sigma is None

    def test_analysis_status(self):
        s = AnalysisStatus(
            fit_full_enabled=True,
            fit_roi_enabled=False,
            x_fit=FitResultSchema(success=True, sigma=12.0),
            y_fit=None,
        )
        assert s.fit_full_enabled is True
        assert s.x_fit.sigma == 12.0
        assert s.y_fit is None


class TestRoiSchemas:
    def test_roi_spec_valid(self):
        r = RoiSpec(x0=10, y0=20, x1=100, y1=200)
        assert r.x0 == 10

    def test_roi_spec_negative_rejected(self):
        with pytest.raises(ValidationError):
            RoiSpec(x0=-1, y0=0, x1=100, y1=100)

    def test_roi_state_inactive(self):
        s = RoiState(active=False)
        assert s.roi is None

    def test_roi_state_active(self):
        s = RoiState(active=True, roi=RoiSpec(x0=0, y0=0, x1=50, y1=50))
        assert s.roi.x1 == 50


class TestCentroidSchemas:
    def test_drift_data_no_reference(self):
        d = DriftData(has_reference=False, crosshair_enabled=False)
        assert d.reference is None

    def test_drift_data_with_values(self):
        d = DriftData(
            has_reference=True,
            crosshair_enabled=True,
            reference=CentroidReference(x=100.0, y=100.0),
            live=CentroidReference(x=101.5, y=99.2),
            drift_x=1.5,
            drift_y=-0.8,
        )
        assert d.drift_x == 1.5


class TestDisplaySchemas:
    def test_colormap_set(self):
        c = ColormapSet(name="viridis")
        assert c.name == "viridis"

    def test_theme_info(self):
        t = ThemeInfo(theme="dark")
        assert t.theme == "dark"


class TestOverlaySchemas:
    def test_overlay_settings_partial(self):
        s = OverlaySettings(h_enabled=True)
        assert s.h_enabled is True
        assert s.v_enabled is None  # not set

    def test_overlay_settings_scale_bounds(self):
        with pytest.raises(ValidationError):
            OverlaySettings(scale=0.01)  # too low

        with pytest.raises(ValidationError):
            OverlaySettings(scale=0.60)  # too high

    def test_overlay_state_full(self):
        s = OverlayStateSchema(
            h_enabled=True, h_side="bottom",
            v_enabled=False, v_side="left",
            scale=0.25, show_full=True, show_roi=True,
        )
        assert s.scale == 0.25


class TestTrendingSchemas:
    def test_trending_depth_bounds(self):
        with pytest.raises(ValidationError):
            TrendingDepthSet(depth=10)  # below 50

        with pytest.raises(ValidationError):
            TrendingDepthSet(depth=3000)  # above 2000

        t = TrendingDepthSet(depth=500)
        assert t.depth == 500

    def test_trending_history(self):
        h = TrendingHistory(
            count=2,
            frame_number=[1.0, 2.0],
            sigma_x=[10.0, 11.0],
            sigma_y=[9.0, 10.0],
            centroid_x=[100.0, 101.0],
            centroid_y=[100.0, 99.0],
            roi_sigma_x=[5.0, 5.5],
            roi_sigma_y=[4.0, 4.5],
            drift_x=[0.0, 1.0],
            drift_y=[0.0, -1.0],
        )
        assert h.count == 2
        assert len(h.frame_number) == 2


class TestFrameSchemas:
    def test_frame_metadata(self):
        m = FrameMetadata(
            frame_number=42,
            fps=10.5,
            height=1038,
            width=1300,
            dtype="uint16",
        )
        assert m.frame_number == 42

    def test_frame_data(self):
        fd = FrameData(
            metadata=FrameMetadata(
                frame_number=1, fps=0.0, height=100, width=100, dtype="uint16",
            ),
            image_b64_png="iVBOR...",
        )
        assert fd.image_b64_png.startswith("iVBOR")


class TestConfigSchemas:
    def test_calibration_info(self):
        c = CalibrationInfo(
            is_calibrated=True,
            um_per_pixel=1.8852,
            unit_label="µm",
            description="Fixed calibration",
        )
        assert c.is_calibrated is True

    def test_config_overview(self):
        c = ConfigOverview(
            active_prefix="BL72",
            available_prefixes=["BL31", "BL72"],
            epics={"host": "", "port": 15064},
            display={"enable_fitting": True},
        )
        assert len(c.available_prefixes) == 2
