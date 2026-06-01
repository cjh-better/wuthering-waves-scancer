# -*- coding: utf-8 -*-
"""
Tests for competitive-parity features ported from KuRo_Scanner.

Covers:
  1. AccountManager — CRUD, persistence, singleton
  2. SmsDialog — countdown, code retrieval
  3. MainWindow new features — platform selector, auto-exit, auto-screen,
     login confirmation, account table, bring-to-front, room ID extraction
  4. ConfigManager — new default fields
"""
import json
import os
import sys
import tempfile
import threading
from unittest.mock import patch, MagicMock

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def _qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


@pytest.fixture()
def tmp_accounts_file(tmp_path):
    """Provide a temporary accounts file for AccountManager isolation."""
    return str(tmp_path / "accounts.json")


@pytest.fixture()
def fresh_account_manager(tmp_accounts_file):
    """
    Return a *fresh* AccountManager instance that writes to a temp file,
    without polluting the singleton.
    """
    from utils.account_manager import AccountManager

    # Reset singleton
    AccountManager._instance = None
    AccountManager._lock = threading.Lock()

    original_file = AccountManager.ACCOUNTS_FILE
    AccountManager.ACCOUNTS_FILE = tmp_accounts_file
    mgr = AccountManager()
    yield mgr
    # Restore
    AccountManager._instance = None
    AccountManager.ACCOUNTS_FILE = original_file


@pytest.fixture()
def tmp_config_file(tmp_path):
    return str(tmp_path / "settings.json")


@pytest.fixture()
def fresh_config_manager(tmp_config_file, tmp_path):
    from utils.config_manager import ConfigManager
    ConfigManager._instance = None
    original_file = ConfigManager.CONFIG_FILE
    ConfigManager.CONFIG_FILE = tmp_config_file
    # also patch config_dir so makedirs works correctly
    mgr = ConfigManager()
    mgr.config_dir = str(tmp_path)
    mgr.config_file = tmp_config_file
    mgr.config = mgr._get_default_config()
    yield mgr
    ConfigManager._instance = None
    ConfigManager.CONFIG_FILE = original_file


# =========================================================================
# 1. AccountManager
# =========================================================================

class TestAccountManager:
    """AccountManager CRUD & persistence."""

    def test_singleton(self, fresh_account_manager):
        from utils.account_manager import AccountManager
        mgr2 = AccountManager()
        assert mgr2 is fresh_account_manager

    def test_add_and_size(self, fresh_account_manager):
        mgr = fresh_account_manager
        assert mgr.size() == 0
        mgr.add_account("TestUser", "uid_001", "tok_001", "13800000001")
        assert mgr.size() == 1

    def test_get_fields(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("Alice", "uid_alice", "tok_a", "13900000002")
        idx = 0
        assert mgr.get_account_uid(idx) == "uid_alice"
        assert mgr.get_account_name(idx) == "Alice"
        assert mgr.get_account_token(idx) == "tok_a"
        assert mgr.get_account_mobile(idx) == "13900000002"
        assert mgr.get_account_note(idx) == ""

    def test_set_note(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("Bob", "uid_bob", "tok_b")
        mgr.set_account_note(0, "VIP account")
        assert mgr.get_account_note(0) == "VIP account"

    def test_update_token(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("Carol", "uid_carol", "old_tok")
        mgr.update_account_token(0, "new_tok")
        assert mgr.get_account_token(0) == "new_tok"

    def test_delete(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("A", "u1", "t1")
        mgr.add_account("B", "u2", "t2")
        mgr.delete_account(0)
        assert mgr.size() == 1
        assert mgr.get_account_uid(0) == "u2"

    def test_find_by_uid(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("D", "uid_d", "t")
        mgr.add_account("E", "uid_e", "t")
        assert mgr.find_index_by_uid("uid_e") == 1
        assert mgr.find_index_by_uid("nonexist") is None

    def test_has_uid(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("F", "uid_f", "t")
        assert mgr.has_uid("uid_f") is True
        assert mgr.has_uid("uid_x") is False

    def test_persistence(self, fresh_account_manager, tmp_accounts_file):
        """Accounts survive a reload from disk."""
        mgr = fresh_account_manager
        mgr.add_account("Persist", "uid_p", "tok_p", "1380000")

        # Read the JSON file directly
        with open(tmp_accounts_file, "r", encoding="utf-8") as f:
            data = json.load(f)
        assert len(data) == 1
        assert data[0]["uid"] == "uid_p"

    def test_out_of_bounds_returns_empty(self, fresh_account_manager):
        mgr = fresh_account_manager
        assert mgr.get_account(99) is None
        assert mgr.get_account_uid(99) == ""
        assert mgr.get_account_name(-1) == ""

    def test_all_accounts(self, fresh_account_manager):
        mgr = fresh_account_manager
        mgr.add_account("G", "ug", "tg")
        mgr.add_account("H", "uh", "th")
        all_acc = mgr.all_accounts()
        assert len(all_acc) == 2
        assert all_acc[0]["name"] == "G"


# =========================================================================
# 2. ConfigManager — new fields
# =========================================================================

class TestConfigManagerNewFields:

    def test_default_has_auto_screen(self, fresh_config_manager):
        assert fresh_config_manager.get("auto_screen") is False

    def test_default_has_default_account(self, fresh_config_manager):
        assert fresh_config_manager.get("default_account") == ""

    def test_default_has_auto_exit(self, fresh_config_manager):
        assert fresh_config_manager.get("auto_exit") is False

    def test_version_is_2(self, fresh_config_manager):
        assert fresh_config_manager.get("version") == "2.0"

    def test_set_and_get(self, fresh_config_manager):
        fresh_config_manager.set("auto_exit", True)
        assert fresh_config_manager.get("auto_exit") is True

    def test_set_default_account(self, fresh_config_manager):
        fresh_config_manager.set("default_account", "uid_123")
        assert fresh_config_manager.get("default_account") == "uid_123"


# =========================================================================
# 3. SmsDialog — UI
# =========================================================================

class TestSmsDialog:

    def test_dialog_creation(self):
        with patch("utils.kuro_api.KuroAPI.send_sms", return_value={"code": 200}):
            from ui.sms_dialog import SmsDialog
            dlg = SmsDialog("tok", "13800001234")
            assert dlg.windowTitle() == "短信验证"
            assert dlg.get_sms_code() == ""
            assert dlg.get_auto_login() is False
            dlg.close()

    def test_countdown_starts(self):
        with patch("utils.kuro_api.KuroAPI.send_sms", return_value={"code": 200}):
            from ui.sms_dialog import SmsDialog
            dlg = SmsDialog("tok", "13800001234")
            assert dlg.send_btn.isEnabled() is False
            assert "重新发送" in dlg.send_btn.text()
            dlg.close()

    def test_confirm_sets_code(self):
        with patch("utils.kuro_api.KuroAPI.send_sms", return_value={"code": 200}):
            from ui.sms_dialog import SmsDialog
            dlg = SmsDialog("tok", "13800001234")
            dlg.code_input.setText("123456")
            dlg._on_confirm()
            assert dlg.get_sms_code() == "123456"
            assert dlg.get_auto_login() is True  # default checked


# =========================================================================
# 4. MainWindow — room ID extraction
# =========================================================================

class TestRoomIdExtraction:

    def _make_window(self):
        """Create a MainWindow with heavy deps mocked out."""
        with patch("ui.main_window.ScanWindow"), \
             patch("ui.main_window.LoginDialog"):
            from ui.main_window import MainWindow
            win = MainWindow()
        return win

    def test_douyin_pure_id(self):
        win = self._make_window()
        assert win.extract_room_id("7318296342388083201", "douyin") == "7318296342388083201"
        win.close()

    def test_douyin_url(self):
        win = self._make_window()
        assert win.extract_room_id("https://live.douyin.com/123456", "douyin") == "123456"
        win.close()

    def test_douyin_room_id_param(self):
        win = self._make_window()
        url = "https://webcast.amemv.com/douyin/webcast/reflow/xxx?room_id=7318296342388083201"
        assert win.extract_room_id(url, "douyin") == "7318296342388083201"
        win.close()

    def test_bilibili_url(self):
        win = self._make_window()
        assert win.extract_room_id("https://live.bilibili.com/21452505", "bilibili") == "21452505"
        win.close()

    def test_fallback_long_number(self):
        win = self._make_window()
        assert win.extract_room_id("room 99991234", "douyin") == "99991234"
        win.close()

    def test_empty_returns_empty(self):
        win = self._make_window()
        assert win.extract_room_id("abc", "douyin") == ""
        win.close()


# =========================================================================
# 5. MainWindow — account table & config integration
# =========================================================================

class TestMainWindowAccountIntegration:

    @pytest.fixture(autouse=True)
    def setup_clean_managers(self, tmp_path):
        """Isolate singleton state for each test."""
        import utils.account_manager as am_mod
        import utils.config_manager as cm_mod
        import ui.main_window as mw_mod
        from utils.account_manager import AccountManager
        from utils.config_manager import ConfigManager

        AccountManager._instance = None
        AccountManager._lock = threading.Lock()
        AccountManager.ACCOUNTS_FILE = str(tmp_path / "acc.json")

        ConfigManager._instance = None
        ConfigManager.CONFIG_FILE = str(tmp_path / "cfg.json")
        cfg = ConfigManager()
        cfg.config_dir = str(tmp_path)
        cfg.config_file = str(tmp_path / "cfg.json")
        cfg.config = cfg._get_default_config()
        acc = AccountManager()

        # Update ALL module-level bindings so every import sees fresh instances
        cm_mod.config_manager = cfg
        am_mod.account_manager = acc
        mw_mod.config_manager = cfg
        mw_mod.account_manager = acc
        yield
        AccountManager._instance = None
        ConfigManager._instance = None

    def _make_window(self):
        with patch("ui.main_window.ScanWindow"), \
             patch("ui.main_window.LoginDialog"):
            from ui.main_window import MainWindow
            win = MainWindow()
        return win

    def test_empty_account_table(self):
        win = self._make_window()
        assert win.account_table.rowCount() == 0
        assert win.selected_account_index == -1
        win.close()

    def test_add_account_updates_table(self):
        from utils.account_manager import account_manager
        account_manager.add_account("TestUser", "uid_t", "tok_t", "138")
        win = self._make_window()
        assert win.account_table.rowCount() == 1
        assert win.account_table.item(0, 1).text() == "uid_t"
        assert win.account_table.item(0, 2).text() == "TestUser"
        win.close()

    def test_auto_exit_checkbox_persists(self):
        from utils.config_manager import config_manager
        # Ensure fresh default
        assert config_manager.get("auto_exit") is False
        win = self._make_window()
        assert win.auto_exit_checkbox.isChecked() is False
        # Toggle it on
        win.auto_exit_checkbox.setChecked(True)
        assert config_manager.get("auto_exit") is True
        win.close()

    def test_auto_screen_needs_default_account(self):
        """auto_screen checkbox should uncheck if no default account."""
        from utils.config_manager import config_manager
        win = self._make_window()
        # No default account set → checkbox should revert (mock the QMessageBox)
        with patch("ui.main_window.QMessageBox"):
            win.auto_screen_checkbox.setChecked(True)
        assert win.auto_screen_checkbox.isChecked() is False
        win.close()

    def test_platform_combo_has_two_options(self):
        win = self._make_window()
        assert win.live_platform_combo.count() == 2
        assert win.live_platform_combo.itemText(0) == "抖音"
        assert win.live_platform_combo.itemText(1) == "B站"
        win.close()


# =========================================================================
# 6. ScanThread — auto_login passthrough
# =========================================================================

class TestScanThreadAutoLogin:

    def test_auto_login_attribute(self):
        from ui.main_window import ScanThread
        t = ScanThread("G152#KURO_test")
        assert t.auto_login is False
        t.auto_login = True
        assert t.auto_login is True
