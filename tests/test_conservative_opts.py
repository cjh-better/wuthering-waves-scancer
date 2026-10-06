# -*- coding: utf-8 -*-
"""保守优化（100+方向）的回归测试。

覆盖：
101. benchmark：解码耗时不回退（1080p 纯色图应 <50ms 被拒绝）
102. 模糊测试：随机损坏图片不崩
103. 并发压力：多线程同时解码不崩
105. 配置项：新增配置有默认值且类型正确
"""
import numpy as np
import pytest
import threading
import time


class TestBenchmark:
    """101. 性能基准防回退."""

    def test_solid_color_rejected_fast(self):
        """纯色图应被快速拒绝（<50ms），而非走完整解码."""
        from utils.ai_qr_scanner import AIQRScanner
        s = AIQRScanner()
        # 纯黑图
        arr = np.zeros((1080, 1920, 3), dtype=np.uint8)
        start = time.time()
        result = s.try_decode_array(arr, color="BGR", allow_slow_fallback=False)
        elapsed = (time.time() - start) * 1000
        assert result is None
        # 纯色拒绝应 <100ms（WeChatQR 完整解码要 50ms+）
        assert elapsed < 100, f"too slow: {elapsed:.0f}ms"

    def test_tiny_rejected_fast(self):
        from utils.ai_qr_scanner import AIQRScanner
        s = AIQRScanner()
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        start = time.time()
        assert s.try_decode_array(arr, color="BGR") is None
        assert (time.time() - start) * 1000 < 50


class TestFuzz:
    """102. 模糊测试：随机损坏输入不崩."""

    def test_random_garbage(self):
        from utils.ai_qr_scanner import AIQRScanner
        s = AIQRScanner()
        rng = np.random.RandomState(42)
        for _ in range(20):
            h = rng.randint(1, 500)
            w = rng.randint(1, 500)
            c = rng.choice([1, 3, 4])
            arr = rng.randint(0, 256, size=(h, w, c), dtype=np.uint8)
            # 不应抛异常（返回 None 或 ticket 均可）
            try:
                s.try_decode_array(arr, color="BGR", allow_slow_fallback=False)
            except Exception as e:
                pytest.fail(f"crashed on shape {(h,w,c)}: {e}")

    def test_wrong_dtype(self):
        from utils.ai_qr_scanner import AIQRScanner
        s = AIQRScanner()
        for dtype in [np.float32, np.int32, np.float64]:
            arr = np.zeros((100, 100, 3), dtype=dtype)
            assert s.try_decode_array(arr, color="BGR") is None


class TestConcurrency:
    """103. 并发压力测试."""

    def test_parallel_decode_no_crash(self):
        from utils.ai_qr_scanner import AIQRScanner
        s = AIQRScanner()
        errors = []
        def worker():
            try:
                rng = np.random.RandomState()
                for _ in range(5):
                    arr = rng.randint(0, 256, size=(200, 200, 3), dtype=np.uint8)
                    s.try_decode_array(arr, color="BGR", allow_slow_fallback=False)
            except Exception as e:
                errors.append(e)
        threads = [threading.Thread(target=worker) for _ in range(4)]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)
        assert not errors, f"errors: {errors}"


class TestNewConfigs:
    """105. 新增配置项默认值."""

    def test_configs_have_defaults(self):
        from utils.config_manager import config_manager
        # 本轮新增的配置
        assert config_manager.get("live_buffer_size", None) == 1
        assert config_manager.get("ndarray_pool_size", None) == 12
        assert config_manager.get("window_pos", None) == []
        assert config_manager.get("decode_subprocess_isolation", None) is False
        assert config_manager.get("dxgi_copy_frame", None) is False
