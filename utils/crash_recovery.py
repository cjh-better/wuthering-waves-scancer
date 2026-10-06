# -*- coding: utf-8 -*-
"""
崩溃自动恢复：native segfault 导致进程退出后，下次启动自动恢复监控。

原理：
- 正常退出时写 clean_exit 标记文件
- 启动时若监控状态文件存在但无 clean_exit 标记 → 上次是崩溃
- 自动用保存的房间/平台参数重启监控
"""
import json
import os
from typing import Optional, Dict

from utils.log import get_logger

logger = get_logger("CrashRecovery")


def _state_dir() -> str:
    # 与 config 同目录
    from utils.config_manager import config_manager
    cfg_path = getattr(config_manager, "_config_path", "config/settings.json")
    return os.path.dirname(os.path.abspath(cfg_path))


def _marker_path() -> str:
    return os.path.join(_state_dir(), ".clean_exit")

def _monitor_state_path() -> str:
    return os.path.join(_state_dir(), ".monitor_state.json")


def mark_clean_exit() -> None:
    """正常退出时调用，写标记。"""
    try:
        with open(_marker_path(), "w") as f:
            f.write("ok")
    except Exception:
        pass


def clear_clean_exit() -> None:
    """启动时调用，清除标记（若进程崩溃，标记会残留缺失）。"""
    try:
        if os.path.exists(_marker_path()):
            os.remove(_marker_path())
    except Exception:
        pass


def was_crash() -> bool:
    """上次是否为崩溃退出（有监控状态但无 clean 标记）。"""
    try:
        return os.path.exists(_monitor_state_path()) and not os.path.exists(_marker_path())
    except Exception:
        return False


def save_monitor_state(room_id: str, platform: str) -> None:
    """保存监控状态（开始监控时调用）。"""
    try:
        with open(_monitor_state_path(), "w", encoding="utf-8") as f:
            json.dump({"room_id": room_id, "platform": platform}, f)
    except Exception:
        pass


def clear_monitor_state() -> None:
    """清除监控状态（停止监控时调用）。"""
    try:
        if os.path.exists(_monitor_state_path()):
            os.remove(_monitor_state_path())
    except Exception:
        pass


def load_monitor_state() -> Optional[Dict[str, str]]:
    """读取保存的监控状态。"""
    try:
        with open(_monitor_state_path(), "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None
