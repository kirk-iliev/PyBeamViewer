"""Tests for BEAMVIEWER_CONFIG env var support in config loader."""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from mcp_servers.beam_viewer.config.config import _get_config_path, load_config

# Minimal valid config for testing
_MINIMAL_CONFIG = {
    "active_prefix": "TEST",
    "pv_prefixes": {
        "TEST": {
            "image_pv": "TEST:image",
            "width_pv": "TEST:width",
            "height_pv": "TEST:height",
        }
    },
    "epics": {"host": "127.0.0.1", "port": 15064},
}


class TestGetConfigPath:
    """Tests for _get_config_path with BEAMVIEWER_CONFIG env var."""

    def test_default_path_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("BEAMVIEWER_CONFIG", raising=False)
        result = _get_config_path()
        expected = Path(__file__).resolve().parent.parent / "config" / "config.json"
        assert result == expected

    def test_env_var_overrides_default(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom_config.json"
        custom.write_text(json.dumps(_MINIMAL_CONFIG))
        monkeypatch.setenv("BEAMVIEWER_CONFIG", str(custom))
        result = _get_config_path()
        assert result == custom

    def test_empty_string_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BEAMVIEWER_CONFIG", "")
        result = _get_config_path()
        expected = Path(__file__).resolve().parent.parent / "config" / "config.json"
        assert result == expected

    def test_whitespace_only_falls_back_to_default(self, monkeypatch):
        monkeypatch.setenv("BEAMVIEWER_CONFIG", "   ")
        result = _get_config_path()
        expected = Path(__file__).resolve().parent.parent / "config" / "config.json"
        assert result == expected


class TestLoadConfigWithEnvVar:
    """Tests for load_config honouring BEAMVIEWER_CONFIG."""

    def test_load_from_env_var_path(self, monkeypatch, tmp_path):
        custom = tmp_path / "custom_config.json"
        custom.write_text(json.dumps(_MINIMAL_CONFIG))
        monkeypatch.setenv("BEAMVIEWER_CONFIG", str(custom))
        config = load_config()
        assert config["active_prefix"] == "TEST"

    def test_load_from_default_when_env_not_set(self, monkeypatch):
        monkeypatch.delenv("BEAMVIEWER_CONFIG", raising=False)
        config = load_config()
        # Default config.json exists and has an active_prefix key
        assert "active_prefix" in config
