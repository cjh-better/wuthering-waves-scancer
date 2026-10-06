# -*- coding: utf-8 -*-
"""登录链路超时阶梯的测试（本地 mock，不打生产服务器）。

覆盖：
1. _load_timeout_ladder：正常加载 / 非法值回退默认 / 上限 5 阶
2. scan_login：超时才重试，非超时错误不重试
3. 配置可调：改配置即改阶梯
"""
import os
import sys

import pytest
import requests

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.kuro_api import KuroAPI


class TestTimeoutLadder:
    def test_default_ladder(self, monkeypatch):
        # 配置缺失时用默认值：不依赖真实配置文件
        from utils import kuro_api as kuro_mod
        monkeypatch.setattr(kuro_mod, "config_manager", None, raising=False)
        # _load_timeout_ladder 内部 import config_manager，patch 它的 get
        from utils import config_manager as cm_mod
        monkeypatch.setattr(cm_mod.config_manager, "get", lambda k, d=None: d)
        assert KuroAPI._load_timeout_ladder("login_retry_timeouts", [0.8, 1.5, 2.5]) == [
            0.8, 1.5, 2.5,
        ]

    def test_custom_ladder_from_config(self, monkeypatch):
        from utils import config_manager as cm_mod

        mgr = cm_mod.config_manager
        monkeypatch.setattr(mgr, "get", lambda k, d=None: [0.5, 1.0] if k == "login_retry_timeouts" else d)
        assert KuroAPI._load_timeout_ladder("login_retry_timeouts", [0.8, 1.5, 2.5]) == [0.5, 1.0]

    def test_invalid_values_fall_back(self, monkeypatch):
        from utils import config_manager as cm_mod

        mgr = cm_mod.config_manager
        for bad in ([0, -1, "x"], [], "notalist", None):
            monkeypatch.setattr(mgr, "get", lambda k, d=None, b=bad: b)
            assert KuroAPI._load_timeout_ladder("login_retry_timeouts", [0.8, 1.5, 2.5]) == [
                0.8, 1.5, 2.5,
            ]

    def test_max_five_steps(self, monkeypatch):
        from utils import config_manager as cm_mod

        mgr = cm_mod.config_manager
        monkeypatch.setattr(mgr, "get", lambda k, d=None: [0.5] * 10)
        assert len(KuroAPI._load_timeout_ladder("login_retry_timeouts", [0.8])) == 5


class TestScanLoginRetry:
    def _api(self):
        api = KuroAPI.__new__(KuroAPI)
        api.session = requests.Session()
        api.headers = {}
        api.BASE_URL = "http://127.0.0.1:9"  # 不可达，靠 mock session.post
        return api

    def test_timeout_retries_with_ladder(self, monkeypatch):
        api = self._api()
        calls = []

        def fake_post(url, data=None, headers=None, timeout=None):
            calls.append(timeout)
            raise requests.exceptions.Timeout()

        monkeypatch.setattr(api.session, "post", fake_post)
        monkeypatch.setattr(
            KuroAPI, "_load_timeout_ladder", staticmethod(lambda k, d: [0.01, 0.02])
        )
        result = api.scan_login("QR", smart_retry=True)
        assert result["code"] == -1
        assert calls == [0.01, 0.02], "超时应按阶梯重试"

    def test_non_timeout_error_does_not_retry(self, monkeypatch):
        api = self._api()
        calls = []

        def fake_post(url, data=None, headers=None, timeout=None):
            calls.append(timeout)
            raise requests.exceptions.ConnectionError("down")

        monkeypatch.setattr(api.session, "post", fake_post)
        result = api.scan_login("QR", smart_retry=True)
        assert result["code"] == -1
        assert len(calls) == 1, "非超时错误不应重试"

    def test_success_on_second_attempt(self, monkeypatch):
        api = self._api()
        calls = []

        class FakeResp:
            def json(self):
                return {"code": 200, "msg": "ok"}

        def fake_post(url, data=None, headers=None, timeout=None):
            calls.append(timeout)
            if len(calls) == 1:
                raise requests.exceptions.Timeout()
            return FakeResp()

        monkeypatch.setattr(api.session, "post", fake_post)
        monkeypatch.setattr(
            KuroAPI, "_load_timeout_ladder", staticmethod(lambda k, d: [0.01, 0.02, 0.03])
        )
        result = api.scan_login("QR", smart_retry=True)
        assert result["code"] == 200
        assert len(calls) == 2
