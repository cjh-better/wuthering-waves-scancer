# -*- coding: utf-8 -*-
"""抢码战绩统计的测试。"""
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.grab_stats import GrabStats


def test_detect_then_success():
    gs = GrabStats.__new__(GrabStats)
    gs._init()
    gs.record_detected()
    time.sleep(0.05)
    gs.record_login_result(True)
    s = gs.summary()
    assert s["total"] == 1
    assert s["success"] == 1
    assert s["success_rate"] == 100.0
    assert 40 <= s["avg_ms"] <= 500


def test_failed_login_counted():
    gs = GrabStats.__new__(GrabStats)
    gs._init()
    gs.record_detected()
    gs.record_login_result(False)
    gs.record_detected()
    gs.record_login_result(True)
    s = gs.summary()
    assert s["total"] == 2
    assert s["success"] == 1
    assert s["failed"] == 1
    assert s["success_rate"] == 50.0


def test_result_without_detect_ignored():
    gs = GrabStats.__new__(GrabStats)
    gs._init()
    gs.record_login_result(True)  # 没有先 record_detected，应忽略
    assert gs.summary()["total"] == 0


def test_reset():
    gs = GrabStats.__new__(GrabStats)
    gs._init()
    gs.record_detected()
    gs.record_login_result(True)
    gs.reset()
    assert gs.summary()["total"] == 0


def test_empty_summary():
    gs = GrabStats.__new__(GrabStats)
    gs._init()
    s = gs.summary()
    assert s["total"] == 0
    assert s["success_rate"] == 0.0
