# -*- coding: utf-8 -*-
"""速度模式预设的测试。"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def test_presets_have_required_keys():
    from utils.speed_presets import PRESETS
    required = {
        "live_scan_frame_stride", "live_decode_queue_size",
        "live_decode_budget_ms", "live_frame_diff_enabled",
        "live_frame_diff_threshold", "live_safety_net_stride",
        "login_retry_timeouts", "roleinfo_retry_timeouts",
    }
    for name, preset in PRESETS.items():
        assert required <= set(preset["values"]), f"{name} 缺键"


def test_extreme_is_fastest():
    from utils.speed_presets import PRESETS
    assert PRESETS["extreme"]["values"]["live_scan_frame_stride"] <= \
        PRESETS["balanced"]["values"]["live_scan_frame_stride"] <= \
        PRESETS["powersave"]["values"]["live_scan_frame_stride"]
    assert PRESETS["extreme"]["values"]["live_decode_budget_ms"] <= \
        PRESETS["powersave"]["values"]["live_decode_budget_ms"]


def test_apply_preset_writes_config(tmp_path, monkeypatch):
    # 注意：直接 patch speed_presets 模块命名空间里的 config_manager 引用，
    # 而不是单例对象的方法——fresh_config_manager fixture 会重置单例，
    # 对象同一性不可靠。
    from utils import speed_presets as sp_mod

    written = {}

    class FakeConfig:
        def set(self, k, v):
            written[k] = v

        def get(self, k, d=None):
            return d

    monkeypatch.setattr(sp_mod, "config_manager", FakeConfig())
    assert sp_mod.apply_preset("extreme") is True
    assert written["live_scan_frame_stride"] == 1
    assert written["speed_preset"] == "extreme"
    assert sp_mod.apply_preset("nonexistent") is False


def test_current_preset_defaults_balanced(monkeypatch):
    from utils import speed_presets as sp_mod

    class FakeConfig:
        def get(self, k, d=None):
            return d

    monkeypatch.setattr(sp_mod, "config_manager", FakeConfig())
    assert sp_mod.current_preset() == "balanced"
