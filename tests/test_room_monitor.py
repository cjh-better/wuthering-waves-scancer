# -*- coding: utf-8 -*-
"""开播监控线程的测试（适配器全部 mock，不打真实网络）。"""
import os
import sys
import time

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _make_monitor(statuses):
    """statuses: {(platform, room_id): status_name}"""
    from utils.room_monitor import RoomMonitorThread
    from utils.platforms.base import LiveStreamStatus

    m = RoomMonitorThread()

    def fake_check(session, platform, room_id):
        return statuses.get((platform, room_id), "NotLive"), "mock"

    m._check_one = fake_check
    return m


def test_live_transition_emits_notification(qapp):
    m = _make_monitor({("douyin", "123"): "NotLive"})
    lives = []
    m.room_live.connect(lambda p, r, t: lives.append((p, r, t)),
                        type=__import__("PySide6.QtCore", fromlist=["Qt"]).Qt.ConnectionType.DirectConnection)
    m.set_rooms([("douyin", "123", "主播A")])
    m._interval = 0.05  # 绕过 set_interval 的 10s 下限
    m.start_monitoring()
    try:
        time.sleep(0.3)  # 第一轮：未开播，无通知
        assert lives == []
        # 主播开播
        m._check_one = lambda s, p, r: ("Normal", "mock")
        time.sleep(0.3)
        assert lives == [("douyin", "123", "主播A")]
        # 保持开播：不再重复通知
        time.sleep(0.3)
        assert len(lives) == 1
    finally:
        m.stop_monitoring()
        m.wait(3000)


def test_status_signal_emitted(qapp):
    m = _make_monitor({("bilibili", "456"): "Normal"})
    got = []
    from PySide6.QtCore import Qt
    m.room_status.connect(lambda p, r, s, t: got.append(s),
                          type=Qt.ConnectionType.DirectConnection)
    m.set_rooms([("bilibili", "456", "")])
    m._interval = 0.05  # 绕过 set_interval 的 10s 下限
    m.start_monitoring()
    try:
        time.sleep(0.3)
        assert "Normal" in got
    finally:
        m.stop_monitoring()
        m.wait(3000)


def test_check_one_never_raises():
    from utils.room_monitor import RoomMonitorThread
    m = RoomMonitorThread()
    # 适配器抛异常也应被吞掉，返回 Error
    import utils.room_monitor as rm_mod
    orig = rm_mod.logger
    status, _ = m._check_one(None, "douyin", "!!!invalid!!!")
    assert status in ("NotLive", "Error", "Absent", "Normal")
