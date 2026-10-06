# -*- coding: utf-8 -*-
"""解码器 hang 隔离与退出清理的回归测试。

覆盖审计修复：
1. try_decode_parallel：单个候选抛异常不拖死其他候选；全部失败返回 None
2. AIQRScanner.shutdown()：幂等，关闭后不再接受新任务
3. sr_net 有独立锁，不跟 WeChatQR 抢 _decode_lock
"""
import os
import sys
import time

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture()
def scanner():
    from utils.ai_qr_scanner import AIQRScanner

    s = AIQRScanner()
    yield s
    # 每个测试后清理，避免线程池泄漏到其他测试
    s.shutdown()


def _blank(name="blank"):
    return (name, Image.new("RGB", (64, 64), "white"))


class TestTryDecodeParallelRobustness:
    def test_single_candidate_exception_does_not_kill_others(self, scanner, monkeypatch):
        """一个候选抛异常，其他候选仍能返回结果。"""
        calls = []

        def fake_decode(img, allow_slow_fallback=True):
            calls.append(img)
            if len(calls) == 1:
                raise RuntimeError("boom")
            return "QR:hello"

        monkeypatch.setattr(scanner, "try_decode_qr", fake_decode)
        result = scanner.try_decode_parallel([_blank("a"), _blank("b"), _blank("c")])
        assert result is not None
        assert result[0] == "QR:hello"

    def test_all_fail_returns_none(self, scanner, monkeypatch):
        monkeypatch.setattr(scanner, "try_decode_qr", lambda img, allow_slow_fallback=True: None)
        assert scanner.try_decode_parallel([_blank()]) is None

    def test_all_raise_returns_none(self, scanner, monkeypatch):
        def boom(img, allow_slow_fallback=True):
            raise RuntimeError("boom")

        monkeypatch.setattr(scanner, "try_decode_qr", boom)
        assert scanner.try_decode_parallel([_blank("a"), _blank("b")]) is None

    def test_hang_bounded_by_timeout(self, scanner, monkeypatch):
        """worker hang 住时，调用方在超时内返回，不永久卡死。"""
        import utils.ai_qr_scanner as mod

        monkeypatch.setattr(mod, "_PARALLEL_DECODE_TIMEOUT_S", 0.5)

        def hang(img, allow_slow_fallback=True):
            time.sleep(5)  # 保持 < 套件容忍度；executor 线程非守护，退出时会等它
            return "QR:never"

        monkeypatch.setattr(scanner, "try_decode_qr", hang)
        start = time.monotonic()
        assert scanner.try_decode_parallel([_blank()]) is None
        elapsed = time.monotonic() - start
        assert elapsed < 10, f"hang 未被超时隔离，耗时 {elapsed:.1f}s"


class TestExecutorShutdown:
    def test_shutdown_idempotent(self, scanner):
        scanner.shutdown()
        scanner.shutdown()  # 第二次不抛异常

    def test_shutdown_rejects_new_tasks(self, scanner):
        scanner.shutdown()
        with pytest.raises(RuntimeError):
            scanner.parallel_executor.submit(lambda: None)

    def test_sr_has_dedicated_lock(self, scanner):
        # sr_net 的 forward 不能跟 WeChatQR 抢同一把锁
        assert scanner._sr_lock is not scanner._decode_lock


class TestAllowSlowFallback:
    def test_slow_fallback_skipped_when_disallowed(self, scanner, monkeypatch):
        """allow_slow_fallback=False 时跳过 pyzbar（WeChatQR 已尝试）。"""
        import utils.ai_qr_scanner as mod

        # 确保 WeChatQR 可用且未命中
        monkeypatch.setattr(scanner, "wechat_detector", object())
        monkeypatch.setattr(mod, "OPENCV_AVAILABLE", True)

        pyzbar_calls = []
        monkeypatch.setattr(mod, "decode", lambda img: pyzbar_calls.append(img) or [])

        import numpy as np

        # mock wechat_detector.detectAndDecode 返回空
        # 注意：实际解码走 _get_thread_detector() 的 thread-local 实例，
        # 直接 mock 该方法才能生效
        class FakeDetector:
            def detectAndDecode(self, img):
                return [], None

        monkeypatch.setattr(scanner, "_get_thread_detector", lambda: FakeDetector())
        # 用噪声图而非纯黑图：纯色图会被"纯色快速拒绝"优化提前拦掉，
        # 测试的是 fallback 逻辑，需要能通过前置检查的图像
        rng = np.random.default_rng(42)
        img = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)

        assert scanner.try_decode_array(img, allow_slow_fallback=False) is None
        assert pyzbar_calls == [], "pyzbar 不应被调用"

        assert scanner.try_decode_array(img, allow_slow_fallback=True) is None
        assert len(pyzbar_calls) == 1, "允许时 pyzbar 应被调用"

    def test_pyzbar_still_runs_when_wechat_unavailable(self, scanner, monkeypatch):
        """WeChatQR 不可用时，即使 disallow，pyzbar 也必须跑（唯一解码器）。"""
        import utils.ai_qr_scanner as mod

        monkeypatch.setattr(scanner, "wechat_detector", None)
        # 阻止 _ensure_models() 重建 detector
        monkeypatch.setattr(scanner, "_ensure_models", lambda: None)
        pyzbar_calls = []
        monkeypatch.setattr(mod, "decode", lambda img: pyzbar_calls.append(img) or [])

        import numpy as np

        # 用噪声图而非纯黑图：纯色图会被"纯色快速拒绝"优化提前拦掉
        rng = np.random.default_rng(42)
        img = rng.integers(0, 256, (64, 64, 3), dtype=np.uint8)
        scanner.try_decode_array(img, allow_slow_fallback=False)
        assert len(pyzbar_calls) == 1
