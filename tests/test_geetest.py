# -*- coding: utf-8 -*-
"""
Tests for the GeeTest v4 dialog (ui.geetest_dialog) and the
KuroAPI captcha heuristic.

The dialog must degrade gracefully when QtWebEngine is unavailable
(the case on this Linux CI box): no crash, clear message, and
get_validate_result() -> None.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication, QDialog

from ui.geetest_dialog import (
    GT4_CAPTCHA_ID,
    WEBENGINE_AVAILABLE,
    GeeTestDialog,
)
from utils.kuro_api import KuroAPI


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestGeeTestDialog:
    def test_captcha_id_matches_cpp_original(self):
        # Must stay in sync with KuRo_Scanner's WindowGeeTest.
        assert GT4_CAPTCHA_ID == "3f7e2d848ce0cb7e7d019d621e556ce2"

    def test_constructs_without_webengine(self):
        # Must never crash even when the browser component is missing.
        dlg = GeeTestDialog()
        try:
            assert dlg.get_validate_result() is None
        finally:
            dlg.close()

    def test_js_result_accepts_validate_payload(self):
        dlg = GeeTestDialog()
        try:
            dlg._on_js_result('{"lot_number": "abc", "captcha_output": "x"}')
            assert dlg._result == {"lot_number": "abc", "captcha_output": "x"}
            assert dlg.result() == QDialog.Accepted
        finally:
            dlg.close()

    def test_js_result_rejects_error_payload(self):
        dlg = GeeTestDialog()
        try:
            dlg._on_js_result('{"error": "geetest_failed"}')
            assert dlg._result is None
            assert dlg.result() == QDialog.Rejected
        finally:
            dlg.close()

    def test_js_result_ignores_garbage(self):
        dlg = GeeTestDialog()
        try:
            dlg._on_js_result("not json")
            dlg._on_js_result("")
            dlg._on_js_result(None)
            assert dlg._result is None
        finally:
            dlg.close()


class TestCaptchaHeuristic:
    def test_success_never_requires_captcha(self):
        assert KuroAPI.is_captcha_required({"code": 200, "msg": "ok"}) is False

    def test_captcha_keywords_trigger(self):
        assert (
            KuroAPI.is_captcha_required({"code": 500, "msg": "请完成极验验证"})
            is True
        )
        assert (
            KuroAPI.is_captcha_required({"code": 500, "msg": "geetest required"})
            is True
        )
        assert (
            KuroAPI.is_captcha_required({"code": 500, "msg": "请拖动滑块完成验证"})
            is True
        )

    def test_unrelated_failure_does_not_trigger(self):
        # Conservative: ordinary failures must not pop the captcha window.
        assert (
            KuroAPI.is_captcha_required({"code": 500, "msg": "发送频繁，请稍后再试"})
            is False
        )
        assert KuroAPI.is_captcha_required({"code": -1, "msg": "请求失败"}) is False
        assert KuroAPI.is_captcha_required(None) is False
        assert KuroAPI.is_captcha_required("oops") is False

    def test_send_sms_accepts_geetest_data(self):
        api = KuroAPI()
        captured = {}

        class FakeResp:
            def json(self):
                return {"code": 200}

        def fake_post(url, data=None, headers=None, timeout=None):
            captured["data"] = data
            return FakeResp()

        api.session.post = fake_post
        api.send_sms('{"lot_number": "abc"}')
        assert captured["data"] == {"geeTestData": '{"lot_number": "abc"}'}

    def test_send_sms_default_unchanged(self):
        # Default call keeps the old wire format: geeTestData=
        api = KuroAPI()
        captured = {}

        class FakeResp:
            def json(self):
                return {"code": 200}

        def fake_post(url, data=None, headers=None, timeout=None):
            captured["data"] = data
            return FakeResp()

        api.session.post = fake_post
        api.send_sms()
        assert captured["data"] == {"geeTestData": ""}
