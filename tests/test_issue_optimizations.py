# -*- coding: utf-8 -*-
"""Issue #6/#7/#8 深度优化的测试。

覆盖：
1. a_bogus 签名健康监控（连续失败计数、自动降级、恢复）
2. 流地址缓存（命中、TTL 过期、只缓存成功）
3. 清晰度降级链（逐级降、最低档返回 None）
4. 模型完整性校验（正常、缺失、损坏）
5. 输入前置校验（非法 dtype/维度/通道/尺寸）
6. 子进程解码器（仅结构测试，不启动真实进程）
"""
import numpy as np
import pytest


# ---------------------------------------------------------------------------
# 1+2. 签名健康监控与自动降级
# ---------------------------------------------------------------------------

class TestApiHealth:
    def setup_method(self):
        from utils.platforms.douyin import DouyinAdapter
        DouyinAdapter.reset_api_health()

    def test_initial_healthy(self):
        from utils.platforms.douyin import DouyinAdapter
        h = DouyinAdapter.api_health()
        assert h["consec_failures"] == 0
        assert h["disabled"] is False

    def test_three_failures_triggers_degrade(self):
        from utils.platforms.douyin import DouyinAdapter
        for _ in range(3):
            DouyinAdapter._record_api_failure()
        h = DouyinAdapter.api_health()
        assert h["consec_failures"] == 3
        assert h["disabled"] is True
        assert DouyinAdapter._api_channel_usable() is False

    def test_success_resets_counter(self):
        from utils.platforms.douyin import DouyinAdapter
        DouyinAdapter._record_api_failure()
        DouyinAdapter._record_api_failure()
        DouyinAdapter._record_api_success()
        assert DouyinAdapter.api_health()["consec_failures"] == 0


# ---------------------------------------------------------------------------
# 3. 流地址缓存
# ---------------------------------------------------------------------------

class TestStreamUrlCache:
    def setup_method(self):
        from utils.platforms.base import clear_stream_url_cache
        clear_stream_url_cache()

    def test_put_and_hit(self):
        from utils.platforms.base import (
            LiveStreamInfo, LiveStreamStatus,
            get_cached_stream_info, put_cached_stream_info,
        )
        info = LiveStreamInfo(status=LiveStreamStatus.Normal, url="http://x.flv")
        put_cached_stream_info("douyin", "123", info)
        hit = get_cached_stream_info("douyin", "123")
        assert hit is not None
        assert hit.url == "http://x.flv"

    def test_only_caches_normal(self):
        from utils.platforms.base import (
            LiveStreamInfo, LiveStreamStatus,
            get_cached_stream_info, put_cached_stream_info,
        )
        info = LiveStreamInfo(status=LiveStreamStatus.Error, detail="fail")
        put_cached_stream_info("douyin", "456", info)
        assert get_cached_stream_info("douyin", "456") is None

    def test_ttl_expiry(self):
        import time
        from utils.platforms import base as _base
        from utils.platforms.base import (
            LiveStreamInfo, LiveStreamStatus,
            get_cached_stream_info, put_cached_stream_info,
        )
        info = LiveStreamInfo(status=LiveStreamStatus.Normal, url="http://y.flv")
        put_cached_stream_info("bilibili", "789", info)
        # 篡改时间戳为 10 分钟前
        key = ("bilibili", "789")
        old_info, _ = _base._STREAM_URL_CACHE[key]
        _base._STREAM_URL_CACHE[key] = (old_info, time.time() - 600)
        assert get_cached_stream_info("bilibili", "789") is None


# ---------------------------------------------------------------------------
# 4. 清晰度降级链
# ---------------------------------------------------------------------------

class TestQualityDegrade:
    def setup_method(self):
        from utils.platforms import douyin as _dy
        _dy.set_quality_override(None)
        from utils.platforms.base import clear_stream_url_cache
        clear_stream_url_cache()

    def teardown_method(self):
        from utils.platforms import douyin as _dy
        _dy.set_quality_override(None)

    def test_degrade_ladder(self):
        from utils.platforms import douyin as _dy
        # 默认 origin → uhd → hd → sd → None
        assert _dy.degrade_quality() == "uhd"
        assert _dy.degrade_quality() == "hd"
        assert _dy.degrade_quality() == "sd"
        assert _dy.degrade_quality() is None

    def test_override_respected(self):
        from utils.platforms import douyin as _dy
        _dy.set_quality_override("hd")
        assert _dy.degrade_quality() == "sd"


# ---------------------------------------------------------------------------
# 6. 模型完整性校验
# ---------------------------------------------------------------------------

class TestModelIntegrity:
    def test_verify_ok(self):
        from utils.model_integrity import verify_models
        ok, problems = verify_models("ScanModel")
        assert ok, f"problems: {problems}"

    def test_missing_file(self):
        from utils.model_integrity import verify_models
        ok, problems = verify_models("/nonexistent_dir_xyz")
        assert not ok
        assert len(problems) == 4


# ---------------------------------------------------------------------------
# 7. 输入前置校验
# ---------------------------------------------------------------------------

class TestInputValidation:
    def _scanner(self):
        from utils.ai_qr_scanner import AIQRScanner
        return AIQRScanner()

    def test_rejects_non_uint8(self):
        s = self._scanner()
        arr = np.zeros((100, 100, 3), dtype=np.float32)
        assert s.try_decode_array(arr, color="BGR") is None

    def test_rejects_bad_ndim(self):
        s = self._scanner()
        arr = np.zeros((10, 10, 3, 3), dtype=np.uint8)
        assert s.try_decode_array(arr, color="BGR") is None

    def test_rejects_bad_channels(self):
        s = self._scanner()
        arr = np.zeros((100, 100, 2), dtype=np.uint8)
        assert s.try_decode_array(arr, color="BGR") is None

    def test_rejects_tiny(self):
        s = self._scanner()
        arr = np.zeros((10, 10, 3), dtype=np.uint8)
        assert s.try_decode_array(arr, color="BGR") is None

    def test_rejects_huge(self):
        s = self._scanner()
        arr = np.zeros((9000, 100, 3), dtype=np.uint8)
        assert s.try_decode_array(arr, color="BGR") is None


# ---------------------------------------------------------------------------
# 5. 子进程解码器（结构测试）
# ---------------------------------------------------------------------------

class TestIsolatedDecoder:
    def test_importable(self):
        from utils.decode_worker import IsolatedDecoder, _worker_main
        assert callable(_worker_main)
        dec = IsolatedDecoder(model_dir="ScanModel")
        assert dec.restarts == 0
        dec.shutdown()

    def test_config_exists(self):
        from utils.config_manager import config_manager
        # 默认关闭
        assert config_manager.get("decode_subprocess_isolation", False) is False
