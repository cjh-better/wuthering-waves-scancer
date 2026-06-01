# -*- coding: utf-8 -*-
"""
多账号管理器（参考 KuRo_Scanner AccountManager）
支持多账号 JSON 持久化、增删改查
"""
import json
import os
import threading
from typing import List, Optional, Dict, Any


class AccountManager:
    """多账号管理器（单例模式，线程安全）"""

    _instance = None
    _lock = threading.Lock()
    ACCOUNTS_FILE = "config/accounts.json"

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._initialized = False
        return cls._instance

    def __init__(self):
        if self._initialized:
            return
        self._accounts: List[Dict[str, str]] = []
        self._load()
        self._initialized = True

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    def _load(self):
        """从 JSON 文件加载账号列表"""
        if os.path.exists(self.ACCOUNTS_FILE):
            try:
                with open(self.ACCOUNTS_FILE, "r", encoding="utf-8") as f:
                    data = json.load(f)
                if isinstance(data, list):
                    self._accounts = data
                    return
            except Exception as e:
                print(f"[AccountManager] Failed to load accounts: {e}")
        self._accounts = []

    def _sync(self):
        """持久化到 JSON 文件"""
        config_dir = os.path.dirname(self.ACCOUNTS_FILE)
        if config_dir and not os.path.exists(config_dir):
            os.makedirs(config_dir, exist_ok=True)
        try:
            with open(self.ACCOUNTS_FILE, "w", encoding="utf-8") as f:
                json.dump(self._accounts, f, indent=4, ensure_ascii=False)
        except Exception as e:
            print(f"[AccountManager] Failed to save accounts: {e}")

    # ------------------------------------------------------------------
    # CRUD
    # ------------------------------------------------------------------

    def size(self) -> int:
        return len(self._accounts)

    def add_account(self, name: str, uid: str, token: str, mobile: str = ""):
        """添加账号（去重检查由调用方完成）"""
        self._accounts.append({
            "name": name,
            "uid": uid,
            "token": token,
            "mobile": mobile,
            "note": "",
        })
        self._sync()

    def delete_account(self, index: int):
        """按索引删除账号"""
        if 0 <= index < len(self._accounts):
            self._accounts.pop(index)
            self._sync()

    def get_account(self, index: int) -> Optional[Dict[str, str]]:
        if 0 <= index < len(self._accounts):
            return self._accounts[index]
        return None

    def get_account_uid(self, index: int) -> str:
        acc = self.get_account(index)
        return acc["uid"] if acc else ""

    def get_account_name(self, index: int) -> str:
        acc = self.get_account(index)
        return acc["name"] if acc else ""

    def get_account_token(self, index: int) -> str:
        acc = self.get_account(index)
        return acc["token"] if acc else ""

    def get_account_mobile(self, index: int) -> str:
        acc = self.get_account(index)
        return acc.get("mobile", "") if acc else ""

    def get_account_note(self, index: int) -> str:
        acc = self.get_account(index)
        return acc.get("note", "") if acc else ""

    def set_account_note(self, index: int, note: str):
        if 0 <= index < len(self._accounts):
            self._accounts[index]["note"] = note
            self._sync()

    def update_account_token(self, index: int, token: str):
        """更新指定账号的 token"""
        if 0 <= index < len(self._accounts):
            self._accounts[index]["token"] = token
            self._sync()

    def find_index_by_uid(self, uid: str) -> Optional[int]:
        for i, acc in enumerate(self._accounts):
            if acc.get("uid") == uid:
                return i
        return None

    def has_uid(self, uid: str) -> bool:
        return self.find_index_by_uid(uid) is not None

    def all_accounts(self) -> List[Dict[str, str]]:
        return list(self._accounts)


# 全局实例
account_manager = AccountManager()
