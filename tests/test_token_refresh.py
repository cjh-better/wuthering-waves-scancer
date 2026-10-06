# -*- coding: utf-8 -*-
"""Token 过期检测 + 一键续期的逻辑测试。

覆盖：
1. classify_token_check_response：明确过期 / 有效 / 网络失败不得判过期 / 未知
2. 一键续期的数据链路：update_account_token 原位更新 + 手机号取回
3. 续期后状态置回可用
"""
import pytest

from utils.token_status import (
    TOKEN_EXPIRED_CODE,
    classify_token_check_response,
    is_token_expired_code,
)


class TestIsTokenExpiredCode:
    def test_220_is_expired(self):
        assert is_token_expired_code(220) is True
        assert is_token_expired_code(TOKEN_EXPIRED_CODE) is True

    def test_other_codes_not_expired(self):
        for code in (200, 2240, 2209, 500, -1, 0, None, "220"):
            assert is_token_expired_code(code) is False


class TestClassifyTokenCheckResponse:
    def test_expired(self):
        status, msg = classify_token_check_response({"code": 220, "msg": "token expired"})
        assert status == "过期"
        assert "重新获取" in msg  # 指引一键续期，而非"重新添加"

    def test_ok(self):
        status, msg = classify_token_check_response({"code": 200, "data": {}})
        assert status == "可用"
        assert msg == ""

    def test_network_failure_must_not_be_expired(self):
        """网络失败（code=-1）绝不能判成过期，避免断网时误删/误标账号。"""
        status, _ = classify_token_check_response({"code": -1, "msg": "请求超时"})
        assert status == "未知"
        assert status != "过期"

    def test_unknown_code(self):
        status, msg = classify_token_check_response({"code": 500, "msg": "服务器错误"})
        assert status == "未知"
        assert msg == "服务器错误"

    def test_missing_code(self):
        status, _ = classify_token_check_response({})
        assert status == "未知"

    def test_missing_msg_fallback(self):
        status, msg = classify_token_check_response({"code": -1})
        assert status == "未知"
        assert msg  # 有兜底文案，不为空


class TestOneClickRefreshDataPath:
    """一键续期的数据链路：用内存中的 AccountManager 验证。"""

    @pytest.fixture()
    def manager(self, tmp_path, monkeypatch):
        from utils import account_manager as am_mod

        # 隔离单例：每个测试用独立的数据文件
        monkeypatch.setattr(am_mod.AccountManager, "_instance", None)
        data_file = tmp_path / "accounts.json"
        monkeypatch.setattr(
            am_mod.AccountManager, "ACCOUNTS_FILE", str(data_file), raising=False
        )
        mgr = am_mod.AccountManager()
        yield mgr
        monkeypatch.setattr(am_mod.AccountManager, "_instance", None)

    def test_refresh_updates_token_in_place(self, manager):
        manager.add_account("测试", "uid123", "OLD_TOKEN", mobile="13800138000")
        assert manager.size() == 1

        # 模拟过期
        manager.set_account_status(0, "过期", "Token已过期")

        # 模拟一键续期成功：原位更新 token（_on_login_success_add_account 的行为）
        manager.update_account_token(0, "NEW_TOKEN")

        assert manager.size() == 1  # 没有多出账号
        assert manager.get_account_token(0) == "NEW_TOKEN"
        assert manager.get_account_uid(0) == "uid123"  # 同一个账号

    def test_mobile_available_for_prefill(self, manager):
        manager.add_account("测试", "uid123", "TOKEN", mobile="13800138000")
        # 一键续期依赖保存的手机号做预填
        assert manager.get_account_mobile(0) == "13800138000"

    def test_status_back_to_ok_after_refresh(self, manager):
        manager.add_account("测试", "uid123", "OLD", mobile="13800138000")
        manager.set_account_status(0, "过期", "Token已过期")
        manager.update_account_token(0, "NEW")
        # _mark_account_token_fresh 的行为
        manager.set_account_status(0, "可用", "")
        assert manager.get_account_status(0) == "可用"
