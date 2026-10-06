# -*- coding: utf-8 -*-
"""抢码专项优化的回归测试：帧差分触发、快速重连、FLV 优先、跳过 role 校验。"""
import numpy as np
import pytest
from unittest.mock import patch

from utils.frame_diff import FrameChangeDetector
from utils.platforms import bilibili as bilibili_module


def _frame(value=60, size=(720, 1280)):
    return np.full((*size, 3), value, dtype=np.uint8)


class TestFrameChangeDetector:
    def test_first_frame_forces_decode(self):
        d = FrameChangeDetector(threshold=2.5)
        assert d.score(_frame()) == float("inf")

    def test_identical_frames_score_near_zero(self):
        d = FrameChangeDetector(threshold=2.5)
        d.score(_frame(60))
        assert d.score(_frame(60)) < 0.5

    def test_qr_appearance_exceeds_threshold(self):
        d = FrameChangeDetector(threshold=2.5)
        d.score(_frame(60))
        changed = _frame(60)
        changed[80:380, 960:1260] = 255  # 模拟二维码出现（大面积反白）
        assert d.score(changed) > 2.5

    def test_garbage_input_never_raises(self):
        d = FrameChangeDetector()
        assert d.score(None) == 0.0
        assert d.score(np.zeros((0, 0, 3), dtype=np.uint8)) == 0.0

    def test_reset_forgets_baseline(self):
        d = FrameChangeDetector()
        d.score(_frame(60))
        d.score(_frame(60))
        d.reset()
        assert d.score(_frame(60)) == float("inf")

    def test_is_hot_respects_threshold(self):
        d = FrameChangeDetector(threshold=100.0)
        d.score(_frame(60))
        changed = _frame(60)
        changed[80:380, 960:1260] = 255
        # 12.5 分的变化在阈值 100 下不算热
        assert not d.is_hot(changed)


class TestBilibiliFlvPreference:
    def _play_info(self, urls):
        streams = []
        for u in urls:
            streams.append({
                "format": [{
                    "codec": [{
                        "base_url": "/live/",
                        "url_info": [{"host": "https://host/", "extra": u}],
                    }]
                }]
            })
        return {"data": {"playurl_info": {"playurl": {"stream": streams}}}}

    def test_prefers_flv_over_hls(self):
        info = self._play_info(["x.m3u8", "x.flv"])
        url = bilibili_module.parse_play_info(info)
        assert ".flv" in url

    def test_falls_back_when_no_flv(self):
        info = self._play_info(["x.m3u8"])
        url = bilibili_module.parse_play_info(info)
        assert url.startswith("https://host/")

    def test_empty_returns_empty(self):
        assert bilibili_module.parse_play_info({}) == ""


class TestReconnectFastPath:
    def test_fast_path_skips_url_refresh(self):
        """瞬断时应先用当前 URL 立即重试，不触发耗时的 URL 刷新。"""
        from utils.live_stream_scanner import LiveStreamScanner

        scanner = LiveStreamScanner()

        class Cap:
            def isOpened(self):
                return True

            def read(self):
                return True, np.zeros((10, 10, 3), dtype=np.uint8)

            def release(self):
                pass

        with patch.object(scanner, "_open_capture", return_value=Cap()) as m_open, \
             patch.object(scanner, "_refresh_stream_url") as m_refresh:
            scanner.is_running = True
            ok = scanner._try_reconnect("http://fake/live.flv")
            assert ok is True
            m_open.assert_called()
            m_refresh.assert_not_called()

    def test_slow_path_refreshes_after_fast_fails(self):
        from utils.live_stream_scanner import LiveStreamScanner

        scanner = LiveStreamScanner()

        class DeadCap:
            def isOpened(self):
                return False

            def read(self):
                return False, None

            def release(self):
                pass

        with patch.object(scanner, "_open_capture", return_value=DeadCap()), \
             patch.object(
                 scanner, "_refresh_stream_url", return_value=""
             ) as m_refresh, \
             patch("utils.live_stream_scanner.time.sleep"), \
             patch.object(scanner, "_reconnect_config", return_value=(0.01, 2)):
            scanner.is_running = True
            ok = scanner._try_reconnect("http://fake/live.flv")
            assert ok is False
            m_refresh.assert_called()


class TestDiffTriggerIntegration:
    """差分触发进入主循环：突变帧插队、静态帧跳过、首帧必解。"""

    def _run_loop_frames(self, scanner, frames):
        """直接驱动采集循环体的帧处理逻辑（不启动线程）。"""
        decoded = []
        scanner._frame_diff.reset()
        scanner._static_frames = 0
        scanner._frame_queue = __import__("queue").Queue(maxsize=8)
        for f in frames:
            if scanner._diff_enabled:
                if scanner._frame_diff.is_hot(f):
                    scanner._drain_queue()
                    scanner._frame_queue.put_nowait(f)
                    decoded.append("hot")
                    scanner._static_frames = 0
                else:
                    scanner._static_frames += 1
                    if scanner._static_frames >= scanner._safety_net_stride:
                        scanner._frame_queue.put_nowait(f)
                        decoded.append("safety")
                        scanner._static_frames = 0
            else:
                scanner._frame_queue.put_nowait(f)
                decoded.append("stride")
        return decoded

    def test_first_frame_decoded_rest_skipped(self):
        from utils.live_stream_scanner import LiveStreamScanner

        scanner = LiveStreamScanner()
        frames = [_frame(60) for _ in range(10)]
        got = self._run_loop_frames(scanner, frames)
        assert got == ["hot"], f"首帧应解码、其余跳过，实际: {got}"

    def test_changed_frame_jumps_queue(self):
        from utils.live_stream_scanner import LiveStreamScanner

        scanner = LiveStreamScanner()
        frames = [_frame(60) for _ in range(5)]
        changed = _frame(60)
        changed[80:380, 960:1260] = 255
        frames.append(changed)
        frames.extend([_frame(60) for _ in range(5)])
        got = self._run_loop_frames(scanner, frames)
        # 首帧 hot + 白块出现 hot + 白块消失 hot（消失也是突变，值得解码）
        assert got == ["hot", "hot", "hot"], f"实际: {got}"

    def test_safety_net_catches_static_qr(self):
        """差分漏检时，兜底间隔仍会解码（检出率不降）。"""
        from utils.live_stream_scanner import LiveStreamScanner

        scanner = LiveStreamScanner()
        scanner._safety_net_stride = 5
        frames = [_frame(60) for _ in range(12)]
        got = self._run_loop_frames(scanner, frames)
        # 首帧 hot + 第 5、10 帧 safety
        assert got == ["hot", "safety", "safety"], f"实际: {got}"


class TestNewConfigDefaults:
    def test_race_config_keys_exist(self):
        from utils.config_manager import _CONFIG_SCHEMA

        assert _CONFIG_SCHEMA["live_frame_diff_enabled"][1] is True
        assert _CONFIG_SCHEMA["live_frame_diff_threshold"][1] == 2.5
        assert _CONFIG_SCHEMA["live_safety_net_stride"][1] == 30
        assert _CONFIG_SCHEMA["live_skip_role_check"][1] is True
        assert _CONFIG_SCHEMA["live_stream_quality"][1] == "origin"


class TestStreamQualitySelection:
    def _room(self, qualities):
        import json

        data = {
            q: {"main": {"flv": f"https://cdn/{q}.flv"}} for q in qualities
        }
        return {
            "stream_url": {
                "live_core_sdk_data": {
                    "pull_data": {"stream_data": json.dumps({"data": data})}
                }
            }
        }

    def test_default_origin(self):
        from utils.platforms import douyin as dy

        url = dy.parse_stream_url(self._room(["origin", "hd", "sd"]))
        assert "/origin.flv" in url

    def test_preferred_quality_honored(self):
        from utils.platforms import douyin as dy

        url = dy.parse_stream_url(self._room(["origin", "hd", "sd"]), quality="hd")
        assert "/hd.flv" in url

    def test_falls_back_to_origin_when_preferred_missing(self):
        from utils.platforms import douyin as dy

        url = dy.parse_stream_url(self._room(["origin", "sd"]), quality="uhd")
        assert "/origin.flv" in url

    def test_falls_back_to_any_when_origin_missing(self):
        from utils.platforms import douyin as dy

        url = dy.parse_stream_url(self._room(["sd"]), quality="hd")
        assert "/sd.flv" in url
