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
