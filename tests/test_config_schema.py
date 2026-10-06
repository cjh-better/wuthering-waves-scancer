# -*- coding: utf-8 -*-
"""Tests for the config schema (utils.config_manager)."""
import logging
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.config_manager import ConfigManager


@pytest.fixture()
def fresh_config_manager(tmp_path, monkeypatch):
    """A ConfigManager isolated from the real config file."""
    monkeypatch.setattr(
        ConfigManager, "CONFIG_FILE", str(tmp_path / "settings.json")
    )
    ConfigManager._instance = None
    mgr = ConfigManager()
    yield mgr
    ConfigManager._instance = None


class TestConfigSchema:
    def test_defaults_come_from_schema(self, fresh_config_manager):
        schema = fresh_config_manager.schema()
        defaults = fresh_config_manager.get_all()
        for key, (_, default, _) in schema.items():
            assert key in defaults

    def test_known_keys_have_types(self, fresh_config_manager):
        assert fresh_config_manager.get("live_scan_frame_stride") == 3
        assert fresh_config_manager.get("auto_login") is False
        assert fresh_config_manager.get("default_account") == ""

    def test_unknown_key_get_warns(self, fresh_config_manager, caplog):
        with caplog.at_level(logging.WARNING, logger="wws.Config"):
            fresh_config_manager.get("no_such_key_xyz", "dflt")
        assert any("no_such_key_xyz" in r.message for r in caplog.records)

    def test_unknown_key_set_warns_but_writes(self, fresh_config_manager, caplog):
        with caplog.at_level(logging.WARNING, logger="wws.Config"):
            fresh_config_manager.set("no_such_key_xyz", 1, save=False)
        assert any("no_such_key_xyz" in r.message for r in caplog.records)
        assert fresh_config_manager.get("no_such_key_xyz") == 1

    def test_type_mismatch_warns_but_writes(self, fresh_config_manager, caplog):
        with caplog.at_level(logging.WARNING, logger="wws.Config"):
            fresh_config_manager.set("auto_login", "yes", save=False)
        assert any("auto_login" in r.message for r in caplog.records)
        # lenient: value is kept, behaviour unchanged
        assert fresh_config_manager.get("auto_login") == "yes"

    def test_new_key_auto_retry_in_schema(self, fresh_config_manager):
        # auto_retry is used by main_window but was missing from defaults.
        assert "auto_retry" in fresh_config_manager.schema()
