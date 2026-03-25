"""Tests for config.config — configuration management and persistence."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import patch

import numpy as np
import pytest

from config.config import (
    get_active_background_path,
    get_active_prefix,
    get_available_prefixes,
    get_display_settings,
    get_epics_connection,
    get_pv_names,
    get_roi_for_prefix,
    list_saved_backgrounds,
    load_background_from_file,
    load_config,
    load_overlay_settings,
    save_background_to_file,
    save_overlay_settings,
    save_roi_for_prefix,
    set_active_background_path,
)


# ===================================================================
# load_config
# ===================================================================

class TestLoadConfig:
    """Tests for loading the JSON config file."""

    def test_reads_valid_json(self, tmp_config_dir):
        config = load_config()
        assert config["active_prefix"] == "TEST"
        assert "pv_prefixes" in config

    def test_missing_file_raises(self, tmp_path):
        fake = tmp_path / "nonexistent.json"
        with patch("config.config._get_config_path", return_value=fake):
            with pytest.raises(FileNotFoundError):
                load_config()

    def test_malformed_json_raises(self, tmp_path):
        bad = tmp_path / "config.json"
        bad.write_text("{invalid json!!")
        with patch("config.config._get_config_path", return_value=bad):
            with pytest.raises(ValueError, match="Invalid JSON"):
                load_config()


# ===================================================================
# get_pv_names
# ===================================================================

class TestGetPVNames:
    """Tests for PV name lookup."""

    def test_known_prefix(self, tmp_config_dir):
        pvs = get_pv_names("TEST")
        assert pvs["image_pv"] == "TEST:image1:ArrayData"

    def test_default_uses_active(self, tmp_config_dir):
        pvs = get_pv_names()
        assert pvs["image_pv"] == "TEST:image1:ArrayData"

    def test_unknown_prefix_raises(self, tmp_config_dir):
        with pytest.raises(ValueError, match="Unknown PV prefix"):
            get_pv_names("NONEXISTENT")


# ===================================================================
# get_epics_connection / get_display_settings
# ===================================================================

class TestConnectionAndDisplay:
    def test_epics_connection(self, tmp_config_dir):
        conn = get_epics_connection()
        assert conn["host"] == "127.0.0.1"
        assert conn["port"] == 15064

    def test_display_settings(self, tmp_config_dir):
        display = get_display_settings()
        assert display["colormap_name"] == "hot"
        assert display["enable_fitting"] is True

    def test_epics_fallback_on_empty(self, tmp_path):
        """If 'epics' key is missing, return sensible defaults."""
        config = {"pv_prefixes": {}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with patch("config.config._get_config_path", return_value=config_path):
            conn = get_epics_connection()
            assert "host" in conn
            assert "port" in conn


# ===================================================================
# get_available_prefixes / get_active_prefix
# ===================================================================

class TestPrefixLists:
    def test_available_prefixes(self, tmp_config_dir):
        prefixes = get_available_prefixes()
        assert set(prefixes) == {"TEST", "OTHER"}

    def test_active_prefix(self, tmp_config_dir):
        assert get_active_prefix() == "TEST"


# ===================================================================
# ROI persistence
# ===================================================================

class TestROIPersistence:
    def test_save_and_load_roundtrip(self, tmp_config_dir):
        roi = (10, 20, 100, 200)
        save_roi_for_prefix("TEST", roi)
        loaded = get_roi_for_prefix("TEST")
        assert loaded == roi

    def test_save_none_removes(self, tmp_config_dir):
        save_roi_for_prefix("TEST", (1, 2, 3, 4))
        assert get_roi_for_prefix("TEST") is not None
        save_roi_for_prefix("TEST", None)
        assert get_roi_for_prefix("TEST") is None

    def test_missing_prefix_returns_none(self, tmp_config_dir):
        assert get_roi_for_prefix("UNKNOWN") is None

    def test_multiple_prefixes(self, tmp_config_dir):
        save_roi_for_prefix("TEST", (1, 2, 3, 4))
        save_roi_for_prefix("OTHER", (5, 6, 7, 8))
        assert get_roi_for_prefix("TEST") == (1, 2, 3, 4)
        assert get_roi_for_prefix("OTHER") == (5, 6, 7, 8)


# ===================================================================
# Overlay settings persistence
# ===================================================================

class TestOverlayPersistence:
    def test_save_and_load_roundtrip(self, tmp_config_dir):
        settings = {
            "h_enabled": True,
            "h_side": "top",
            "v_enabled": True,
            "v_side": "right",
            "scale": 0.5,
        }
        save_overlay_settings(settings)
        loaded = load_overlay_settings()
        assert loaded == settings

    def test_default_overlay(self, tmp_path):
        """If 'overlay' key is missing, return sensible defaults."""
        config = {"pv_prefixes": {}}
        config_path = tmp_path / "config.json"
        config_path.write_text(json.dumps(config))
        with patch("config.config._get_config_path", return_value=config_path):
            defaults = load_overlay_settings()
            assert "h_enabled" in defaults
            assert "scale" in defaults


# ===================================================================
# Background persistence
# ===================================================================

class TestBackgroundPersistence:
    def test_save_and_load_roundtrip(self, tmp_config_dir):
        frame = np.arange(100, dtype=np.uint16).reshape(10, 10)
        path = save_background_to_file("TEST", frame)
        loaded = load_background_from_file(path)
        np.testing.assert_array_equal(loaded, frame)

    def test_filename_contains_prefix(self, tmp_config_dir):
        frame = np.zeros((5, 5), dtype=np.uint16)
        path = save_background_to_file("MYPREFIX", frame)
        assert "MYPREFIX" in path.name

    def test_list_saved_backgrounds(self, tmp_config_dir):
        import time
        frame = np.zeros((5, 5), dtype=np.uint16)
        save_background_to_file("A", frame)
        save_background_to_file("B", frame)
        # Sleep to ensure the next file gets a distinct timestamp
        time.sleep(1.1)
        save_background_to_file("A", frame)

        all_files = list_saved_backgrounds()
        assert len(all_files) == 3

        a_files = list_saved_backgrounds("A")
        assert len(a_files) == 2
        assert all("A" in p.name for p in a_files)

    def test_active_background_path_roundtrip(self, tmp_config_dir):
        frame = np.zeros((5, 5), dtype=np.uint16)
        path = save_background_to_file("TEST", frame)
        set_active_background_path("TEST", path)
        loaded_path = get_active_background_path("TEST")
        assert loaded_path == path

    def test_active_background_path_none(self, tmp_config_dir):
        assert get_active_background_path("NONEXISTENT") is None

    def test_active_background_path_missing_file(self, tmp_config_dir):
        """If the file has been deleted, get_active_background_path returns None."""
        set_active_background_path("TEST", "/tmp/does_not_exist.npy")
        assert get_active_background_path("TEST") is None

    def test_set_active_background_path_to_none_removes(self, tmp_config_dir):
        frame = np.zeros((5, 5), dtype=np.uint16)
        path = save_background_to_file("TEST", frame)
        set_active_background_path("TEST", path)
        assert get_active_background_path("TEST") is not None
        set_active_background_path("TEST", None)
        assert get_active_background_path("TEST") is None


# ===================================================================
# Config schema validation
# ===================================================================

class TestConfigValidation:
    """Tests for validate_config() via caplog."""

    from config.config import validate_config

    def _config_with(self, prefix_entry: dict) -> dict:
        return {
            "active_prefix": "X",
            "pv_prefixes": {"X": prefix_entry},
            "epics": {"host": "", "port": 15064},
        }

    def test_valid_config_no_warnings(self, caplog):
        import logging
        from config.config import validate_config
        good = {
            "active_prefix": "X",
            "pv_prefixes": {
                "X": {
                    "image_pv": "X:img",
                    "width_pv": "X:w",
                    "height_pv": "X:h",
                }
            },
            "epics": {},
        }
        with caplog.at_level(logging.WARNING, logger="config.config"):
            validate_config(good)
        assert len(caplog.records) == 0

    def test_missing_top_level_key(self, caplog):
        import logging
        from config.config import validate_config
        cfg = {"pv_prefixes": {}, "epics": {}}  # missing active_prefix
        with caplog.at_level(logging.WARNING, logger="config.config"):
            validate_config(cfg)
        assert any("active_prefix" in r.message for r in caplog.records)

    def test_missing_required_pv_key(self, caplog):
        import logging
        from config.config import validate_config
        cfg = self._config_with({"image_pv": "X:img", "width_pv": "X:w"})  # missing height_pv
        with caplog.at_level(logging.WARNING, logger="config.config"):
            validate_config(cfg)
        assert any("height_pv" in r.message for r in caplog.records)

    def test_invalid_fallback_shape_warns(self, caplog):
        import logging
        from config.config import validate_config
        cfg = self._config_with({
            "image_pv": "X:img",
            "width_pv": "X:w",
            "height_pv": "X:h",
            "fallback_shape": [300],  # should be 2 elements
        })
        with caplog.at_level(logging.WARNING, logger="config.config"):
            validate_config(cfg)
        assert any("fallback_shape" in r.message for r in caplog.records)

    def test_negative_fallback_shape_warns(self, caplog):
        import logging
        from config.config import validate_config
        cfg = self._config_with({
            "image_pv": "X:img",
            "width_pv": "X:w",
            "height_pv": "X:h",
            "fallback_shape": [300, -1],  # negative dimension
        })
        with caplog.at_level(logging.WARNING, logger="config.config"):
            validate_config(cfg)
        assert any("fallback_shape" in r.message for r in caplog.records)

    def test_unknown_calibration_method_warns(self, caplog):
        import logging
        from config.config import validate_config
        cfg = self._config_with({
            "image_pv": "X:img",
            "width_pv": "X:w",
            "height_pv": "X:h",
            "calibration": {"method": "laser_interferometry"},
        })
        with caplog.at_level(logging.WARNING, logger="config.config"):
            validate_config(cfg)
        assert any("method" in r.message for r in caplog.records)

    def test_valid_calibration_methods_no_warning(self, caplog):
        import logging
        from config.config import validate_config
        for method in ("fixed", "pinhole", "none"):
            caplog.clear()
            cfg = self._config_with({
                "image_pv": "X:img",
                "width_pv": "X:w",
                "height_pv": "X:h",
                "calibration": {"method": method},
            })
            with caplog.at_level(logging.WARNING, logger="config.config"):
                validate_config(cfg)
            method_warnings = [r for r in caplog.records if "method" in r.message]
            assert len(method_warnings) == 0, f"Unexpected warning for method={method!r}"
