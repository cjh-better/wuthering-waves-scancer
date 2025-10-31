# -*- coding: utf-8 -*-
"""
配置管理器（持久化用户设置）
"""
import json
import os
from typing import Dict, Any


class ConfigManager:
    """配置管理器（单例模式）"""
    
    _instance = None
    CONFIG_FILE = "config/settings.json"
    
    def __new__(cls):
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
    
    def _get_default_config(self) -> Dict[str, Any]:
        """获取默认配置"""
        return {
            "auto_login": False,        # 是否自动登录（检测到QR码立即登录）
            "auto_exit": False,         # 是否登录成功后自动退出
            "auto_start": False,        # 是否启动后自动开始扫描
            "last_token": "",           # 上次登录的token
            "last_uid": "",             # 上次登录的UID
            "window_position": None,    # 窗口位置 [x, y]
            "scan_window_size": [800, 800],  # 扫描窗口大小
            "thread_pool_enabled": False,    # 是否启用多线程池
            "version": "1.0"
        }
    
    def _load_config(self) -> Dict[str, Any]:
        """加载配置文件"""
        # 确保配置目录存在
        if not os.path.exists(self.config_dir):
            try:
                os.makedirs(self.config_dir)
                print(f"[Config] Created config directory: {self.config_dir}")
            except Exception as e:
                print(f"[Config] Failed to create config directory: {e}")
                return self._get_default_config()
        
        # 尝试加载配置文件
        if os.path.exists(self.config_file):
            try:
                with open(self.config_file, 'r', encoding='utf-8') as f:
                    config = json.load(f)
                    print("[Config] Loaded configuration successfully")
                    
                    # 合并默认配置（处理新增配置项）
                    default_config = self._get_default_config()
                    for key, value in default_config.items():
                        if key not in config:
                            config[key] = value
                    
                    return config
            except Exception as e:
                print(f"[Config] Failed to load config file: {e}")
                return self._get_default_config()
        else:
            # 创建默认配置文件
            config = self._get_default_config()
            self._save_config(config)
            print("[Config] Created default configuration file")
            return config
    
    def _save_config(self, config: Dict[str, Any] = None):
        """保存配置到文件"""
        if config is None:
            config = self.config
        
        try:
            with open(self.config_file, 'w', encoding='utf-8') as f:
                json.dump(config, f, indent=4, ensure_ascii=False)
            # print("[Config] Configuration saved successfully")
        except Exception as e:
            print(f"[Config] Failed to save config: {e}")
    
    def get(self, key: str, default=None) -> Any:
        """获取配置项"""
        return self.config.get(key, default)
    
    def set(self, key: str, value: Any, save: bool = True):
        """设置配置项"""
        self.config[key] = value
        if save:
            self._save_config()
    
    def get_all(self) -> Dict[str, Any]:
        """获取所有配置"""
        return self.config.copy()
    
    def update(self, updates: Dict[str, Any], save: bool = True):
        """批量更新配置"""
        self.config.update(updates)
        if save:
            self._save_config()
    
    def reset(self):
        """重置为默认配置"""
        self.config = self._get_default_config()
        self._save_config()
        print("[Config] Configuration reset to defaults")


# 全局配置管理器实例
config_manager = ConfigManager()
