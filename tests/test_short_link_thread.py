# -*- coding: utf-8 -*-
"""分享短链后台解析线程的测试。

回归：短链解析曾在 UI 线程同步阻塞（最长 ~8s 假死），
现已搬到 ShortLinkResolveThread，后台做完再回 UI 线程。
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


def test_short_link_thread_emits_result(qapp, monkeypatch):
    """线程完成后通过 signal 回传 (room_id, platform)，不抛异常。"""
    from ui.main_window import ShortLinkResolveThread
    from utils import room_url

    monkeypatch.setattr(room_url, "resolve_room_id", lambda url, plat, timeout=8.0: "12345")

    received = []
    t = ShortLinkResolveThread("https://v.douyin.com/abc/", "douyin")
    t.result.connect(lambda rid, plat: received.append((rid, plat)))
    t.start()
    assert t.wait(5000), "解析线程 5s 内应完成（mock 无网络）"
    # 给 queued signal 一次事件循环机会
    qapp.processEvents()
    assert received == [("12345", "douyin")]
    t.deleteLater()


def test_short_link_thread_never_raises(qapp, monkeypatch):
    """resolve 抛异常时线程仍正常结束，回传空字符串。"""
    from ui.main_window import ShortLinkResolveThread
    from utils import room_url

    def boom(url, plat, timeout=8.0):
        raise RuntimeError("network down")

    monkeypatch.setattr(room_url, "resolve_room_id", boom)

    received = []
    t = ShortLinkResolveThread("https://v.douyin.com/abc/", "douyin")
    t.result.connect(lambda rid, plat: received.append((rid, plat)))
    t.start()
    assert t.wait(5000)
    qapp.processEvents()
    assert received == [("", "douyin")]
    t.deleteLater()


def test_follow_redirects_total_timeout_bounded():
    """两次尝试平分预算：总量不超过 timeout（closeEvent 的等待依赖此上界）。"""
    import inspect
    from utils import room_url

    src = inspect.getsource(room_url._follow_redirects)
    assert "timeout / 2" in src or "timeout/2" in src
