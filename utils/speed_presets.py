# -*- coding: utf-8 -*-
"""速度模式预设：一键切换 极限 / 均衡 / 省电。

每个预设是一组配置键值，apply() 写入 config_manager。
注意：只覆盖与速度/功耗相关的键，不动账号、窗口等无关配置。
"""
from typing import Dict, Any

from utils.config_manager import config_manager
from utils.log import get_logger


logger = get_logger("SpeedPreset")


PRESETS: Dict[str, Dict[str, Any]] = {
    "extreme": {
        "label": "极限速度",
        "desc": "抢码优先：逐帧扫描、激进阈值，CPU 占用最高",
        "values": {
            "live_scan_frame_stride": 1,
            "live_decode_queue_size": 2,
            "live_decode_budget_ms": 100,
            "live_frame_diff_enabled": True,
            "live_frame_diff_threshold": 1.5,
            "live_safety_net_stride": 15,
            "login_retry_timeouts": [0.5, 1.0, 2.0],
            "roleinfo_retry_timeouts": [0.4, 0.8, 1.5],
        },
    },
    "balanced": {
        "label": "均衡",
        "desc": "默认：速度与 CPU 占用平衡",
        "values": {
            "live_scan_frame_stride": 3,
            "live_decode_queue_size": 2,
            "live_decode_budget_ms": 150,
            "live_frame_diff_enabled": True,
            "live_frame_diff_threshold": 2.5,
            "live_safety_net_stride": 30,
            "login_retry_timeouts": [0.8, 1.5, 2.5],
            "roleinfo_retry_timeouts": [0.6, 1.2, 2.0],
        },
    },
    "powersave": {
        "label": "省电",
        "desc": "低 CPU：降频扫描、迟钝阈值，抢码稍慢",
        "values": {
            "live_scan_frame_stride": 6,
            "live_decode_queue_size": 2,
            "live_decode_budget_ms": 250,
            "live_frame_diff_enabled": True,
            "live_frame_diff_threshold": 4.0,
            "live_safety_net_stride": 90,
            "login_retry_timeouts": [0.8, 1.5, 2.5],
            "roleinfo_retry_timeouts": [0.6, 1.2, 2.0],
        },
    },
}

PRESET_ORDER = ["extreme", "balanced", "powersave"]


def apply_preset(name: str) -> bool:
    """应用预设，返回是否成功。"""
    preset = PRESETS.get(name)
    if not preset:
        return False
    for key, value in preset["values"].items():
        try:
            config_manager.set(key, value)
        except Exception as e:
            logger.warning("[SpeedPreset] 设置 %s=%s 失败: %s", key, value, e)
    config_manager.set("speed_preset", name)
    logger.info("[SpeedPreset] 已应用预设: %s", preset["label"])
    return True


def current_preset() -> str:
    """当前预设名（默认均衡）。"""
    name = config_manager.get("speed_preset", "balanced")
    return name if name in PRESETS else "balanced"
