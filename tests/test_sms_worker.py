# -*- coding: utf-8 -*-
"""短信后台发送的测试。

覆盖：
1. SmsSendWorker 在后台线程执行 send_sms，通过 done signal 回传结果
2. send_sms 抛异常时 worker 不崩溃，回传错误结果
3. gee_test_data 透传
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _run_worker(qapp, gee_data="", monkeypatch=None):
    from ui.sms_dialog import SmsSendWorker
    from utils import kuro_api as kuro_mod

    calls = {}

    def fake_send_sms(gee_test_data=""):
        calls["gee"] = gee_test_data
        if gee_test_data == "RAISE":
            raise RuntimeError("net down")
        return {"code": 200, "msg": "ok"}

    if monkeypatch is not None:
        monkeypatch.setattr(kuro_mod.kuro_api, "send_sms", fake_send_sms)
    else:
        kuro_mod.kuro_api.send_sms = fake_send_sms

    received = []
    w = SmsSendWorker(gee_test_data=gee_data)
    w.done.connect(lambda r: received.append(r))
    w.start()
    assert w.wait(5000), "worker 5s 内应完成"
    qapp.processEvents()
    w.deleteLater()
    return received, calls


def test_worker_emits_result(qapp, monkeypatch):
    received, calls = _run_worker(qapp, monkeypatch=monkeypatch)
    assert len(received) == 1
    assert received[0]["code"] == 200
    assert calls["gee"] == ""


def test_worker_passes_gee_data(qapp, monkeypatch):
    received, calls = _run_worker(qapp, gee_data="GT4DATA", monkeypatch=monkeypatch)
    assert received[0]["code"] == 200
    assert calls["gee"] == "GT4DATA"


def test_worker_exception_isolated(qapp, monkeypatch):
    received, _ = _run_worker(qapp, gee_data="RAISE", monkeypatch=monkeypatch)
    assert len(received) == 1
    assert received[0]["code"] == -1
