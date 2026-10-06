# -*- coding: utf-8 -*-
"""
配置管理器（持久化用户设置）

所有配置项在 ``_CONFIG_SCHEMA`` 中声明：``key: (类型, 默认值, 说明)``。
- 未知 key：读/写时记 warning（帮助发现拼写错误），但不丢弃数据。
- 类型不符：记 warning（不强制转换，避免破坏调用方行为）。
"""
import json
import os
import threading
from typing import Any, Dict, Optional, Tuple, Union


try:
    from utils.log import get_logger
except ImportError:  # pragma: no cover - defensive for odd import orders
    import logging

    def get_logger(name):  # type: ignore
        return logging.getLogger(name)


logger = get_logger("Config")

# key: (允许的类型, 默认值, 说明)
_CONFIG_SCHEMA: Dict[str, Tuple[Union[type, Tuple[type, ...]], Any, str]] = {
    "auto_login": (bool, False, "是否自动登录（检测到QR码立即登录）"),
    "auto_exit": (bool, False, "是否登录成功后自动退出"),
    "auto_screen": (bool, False, "是否启动后自动监视屏幕"),
    "auto_retry": (bool, False, "是否启用自动重试"),
    "default_account": (str, "", "默认账号UID"),
    "last_token": (str, "", "上次登录的token（兼容旧版）"),
    "last_uid": (str, "", "上次登录的UID（兼容旧版）"),
    "window_position": ((list, type(None)), None, "窗口位置 [x, y]"),
    "scan_window_size": (list, [800, 800], "扫描窗口大小"),
    "thread_pool_enabled": (bool, False, "是否启用多线程池"),
    "live_scan_frame_stride": (int, 3, "直播流每几帧扫描一次"),
    "live_decode_queue_size": (int, 2, "直播解码帧队列长度（采集/解码分离，丢旧帧保实时）"),
    "live_decode_budget_ms": (int, 150, "单帧解码耗时预算（毫秒），超过则自适应降频"),
    "live_frame_diff_enabled": (bool, True, "直播帧差分触发（变化才解码，静态帧跳过）"),
    "live_frame_diff_threshold": (float, 2.5, "帧差分突变阈值（64x36灰度absdiff均值），超过则立即解码"),
    "live_safety_net_stride": (int, 30, "差分模式下的兜底全解码间隔（帧数），防差分漏检"),
    "live_skip_role_check": (bool, True, "抢码加速：跳过登录前的roleInfos校验（省一次RTT）"),
    "live_stream_quality": (str, "origin", "抖音取流清晰度偏好：origin=原画(默认，保检出率)/uhd/hd/sd；低清晰度延迟略低但码可能更糊，由review决策"),
    "live_ffmpeg_opts": (str, "", "FFmpeg 拉流参数覆盖（OPENCV_FFMPEG_CAPTURE_OPTIONS 格式）；空=用内置低延迟默认"),
    "monitor_rooms": (list, [], "开播监控的房间列表 [{platform, room_id, name}]"),
    "monitor_interval": (int, 60, "开播监控轮询间隔（秒）"),
    "speed_preset": (str, "balanced", "速度模式预设：extreme/balanced/powersave"),
    "live_hw_decode": (bool, False, "直播流硬件解码（D3D11/DXVA2，需Windows+兼容GPU，默认关闭因兼容性参差）"),
    "live_backend": (str, "opencv", "直播流后端：opencv（默认，稳定）/pyav（需pip install av，更低延迟）"),
    "scheduled_grab_enabled": (bool, False, "定时抢码开关"),
    "scheduled_grab_time": (str, "", "定时抢码时间（HH:MM，24小时制，空=未设置）"),
    "grab_record_enabled": (bool, False, "抢码录像：检出时保存前后N帧（复盘用）"),
    "grab_record_frames": (int, 30, "抢码录像前后各保存帧数"),
    "grab_record_dir": (str, "grab_records", "抢码录像保存目录"),
    "live_proxy": (str, "", "直播流代理（http://host:port，空=直连）"),
    "decode_subprocess_isolation": (bool, False, "子进程隔离解码（native segfault只死worker不闪退，默认关闭，有~1-2s启动开销）"),
    "window_pos": (list, [], "主窗口上次位置 [x, y]"),
    "screen_scan_candidates": (int, 1, "屏幕扫码候选数：1=单候选（快，WeChatQR@0.4已验证全尺寸）/3=三候选（慢，兼容极端码）"),
    "screen_capture_downscale": (float, 1.0, "屏幕截图降采样（4K屏设0.5提速，1.0=不降采样；过小可能丢小码）"),
    "dxgi_copy_frame": (bool, False, "DXGI截图后强制copy一份（若dxcam某版本出现花屏/撕裂时开启，默认零拷贝）"),
    "ndarray_pool_size": (int, 12, "numpy buffer池大小（4-32，覆盖常用截图尺寸）"),
    "live_buffer_size": (int, 1, "直播拉流buffer帧数（1=最低延迟，弱网设3-5防抖）"),
    "login_retry_timeouts": (list, [0.8, 1.5, 2.5], "scanLogin 超时重试阶梯（秒）：仅超时才进下一阶，总和决定最坏等待"),
    "roleinfo_retry_timeouts": (list, [0.6, 1.2, 2.0], "roleInfos 超时重试阶梯（秒）"),
    "version": (str, "3.0", "配置版本"),
}


def _default_for(key: str) -> Any:
    return _CONFIG_SCHEMA[key][1]


def _check_type(key: str, value: Any) -> bool:
    expected = _CONFIG_SCHEMA[key][0]
    return isinstance(value, expected)


class ConfigManager:
    """配置管理器（单例模式，线程安全）"""

    _instance = None
    _lock = threading.Lock()
    CONFIG_FILE = "config/settings.json"

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        """初始化配置管理器"""
        if self._initialized:
            return

        self.config_dir = "config"
        self.config_file = self.CONFIG_FILE
        self.config = self._load_config()
        self._initialized = True

    # ------------------------------------------------------------------
    # Schema
    # ------------------------------------------------------------------

    @staticmethod
    def schema() -> Dict[str, Tuple[Union[type, Tuple[type, ...]], Any, str]]:
        """返回配置 schema（key → (类型, 默认值, 说明)）。"""
        return dict(_CONFIG_SCHEMA)

    @classmethod
    def _get_default_config(cls) -> Dict[str, Any]:
        """获取默认配置（由 schema 生成）"""
        return {key: default for key, (_, default, _) in _CONFIG_SCHEMA.items()}

    def _validate_loaded(self, config: Dict[str, Any]) -> Dict[str, Any]:
        """校验从文件加载的配置：补齐缺失项，对未知 key / 类型不符告警。"""
        for key in config:
            if key not in _CONFIG_SCHEMA:
                logger.warning("[Config] Unknown config key %r (kept as-is)", key)
        for key, (_, default, _) in _CONFIG_SCHEMA.items():
            if key not in config:
                config[key] = default
            elif not _check_type(key, config[key]):
                logger.warning(
                    "[Config] Type mismatch for %r: expected %s, got %s "
                    "(kept as-is)",
                    key,
                    getattr(_CONFIG_SCHEMA[key][0], "__name__",
                            str(_CONFIG_SCHEMA[key][0])),
                    type(config[key]).__name__,
                )
        return config

    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        # 确保配置目录存在
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir)
                logger.info("[Config] Created config directory: %s", self.config_dir)
            except Exception as e:
                logger.warning("[Config] Failed to create config directory: %s", e)
                return self._get_default_config()

        # 尝试加载配置文件
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    logger.info("[Config] Loaded configuration successfully")
                    return self._validate_loaded(config)
            except Exception as e:
                # 优化71：损坏时备份原文件再重建，避免用户配置丢失无迹可寻
                try:
                    import shutil as _shutil
                    from datetime import datetime as _dt
                    bak = self.config_file + ".bak_" + _dt.now().strftime("%Y%m%d_%H%M%S")
                    _shutil.copy2(self.config_file, bak)
                    logger.warning("[Config] 配置文件损坏，已备份到 %s，将使用默认配置", bak)
                except Exception:
                    pass
                logger.warning("[Config] Failed to load config file: %s", e)
                return self._get_default_config()
        else:
            # 创建默认配置文件
            config = self._get_default_config()
            self._save_config(config)
            logger.info("[Config] Created default configuration file")
            return config

    def _save_config(self, config: Optional[Dict[str, Any]] = None):
        """保存配置到文件"""
        if config is None:
            config = self.config

        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
        except Exception as e:
            logger.warning("[Config] Failed to save config: %s", e)

    def get(self, key: str, default=None) -> Any:
        """获取配置项（未知 key 记 warning）"""
        if key not in _CONFIG_SCHEMA:
            logger.warning("[Config] Getting unknown config key %r", key)
        return self.config.get(key, default)

    def set(self, key: str, value: Any, save: bool = True):
        """设置配置项（未知 key / 类型不符记 warning，但仍写入）"""
        if key not in _CONFIG_SCHEMA:
            logger.warning("[Config] Setting unknown config key %r", key)
        elif not _check_type(key, value):
            logger.warning(
                "[Config] Type mismatch for %r: expected %s, got %s",
                key,
                getattr(_CONFIG_SCHEMA[key][0], "__name__",
                        str(_CONFIG_SCHEMA[key][0])),
                type(value).__name__,
            )
        self.config[key] = value
        if save:
            self._save_config()

    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self.config.copy()

    def update(self, updates: Dict[str, Any], save: bool = True):
        """批量更新配置"""
        for key, value in updates.items():
            self.set(key, value, save=False)
        if save:
            self._save_config()

    def reset(self):
        """重置为默认配置"""
        self.config = self._get_default_config()
        self._save_config()
        logger.info("[Config] Configuration reset to defaults")


# 全局配置管理器实例
config_manager = ConfigManager()
