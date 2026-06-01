# -*- coding: utf-8 -*-
"""
Regression tests for LiveStreamScanner.

Covers:
  Original bugs (PR #3):
    1. Stream interruption causes immediate exit with no reconnect attempt.
    2. stop() only sets a flag – if cap.read() blocks, the thread hangs.
    3. QR codes shorter than 24 characters are silently dropped.

  MHY_Scanner optimizations:
    4. LiveStreamInfo unified return type (status + url + headers).
    5. Safe JSON parsing (_safe_json) – returns None instead of raising.
    6. Douyin pull_datas + live_core_sdk_data dual-path fallback.
    7. FFmpeg low-latency parameters are applied when opening a capture.
    8. Bilibili room_init error handling (absent / not-live / malformed).
    9. Platform dispatch via get_live_stream_info().
"""
import json
import sys
import os
import time
import threading
import types
from unittest.mock import patch, MagicMock

import pytest

# Ensure the project root is on sys.path so `utils.*` imports resolve.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication
from utils.live_stream_scanner import (
    LiveStreamScanner,
    LiveStreamInfo,
    LiveStreamStatus,
    DEFAULT_SCAN_FRAME_STRIDE,
)
from utils.qr_payload import extract_kuro_ticket, is_kuro_qr


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def qapp():
    """A single QApplication shared across all tests (required by Qt)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _process_events():
    """Flush pending Qt events so cross-thread signals are delivered."""
    QCoreApplication.processEvents()


def _ok_stream_info(url="http://fake-stream.test/live.flv"):
    """Return a *Normal* LiveStreamInfo pointing at *url*."""
    return LiveStreamInfo(status=LiveStreamStatus.Normal, url=url)


class FakeCapture:
    """Minimal stand-in for cv2.VideoCapture.

    Parameters
    ----------
    frames : list[tuple[bool, object]]
        Sequence of (ret, frame) tuples that ``read()`` will yield.
        After the sequence is exhausted every subsequent read returns
        ``(False, None)``.
    open_ok : bool
        What ``isOpened()`` returns.
    block_on_read : bool
        If True, ``read()`` blocks until ``release()`` is called.
    """

    def __init__(self, frames=None, open_ok=True, block_on_read=False):
        self._frames = list(frames or [])
        self._idx = 0
        self._open = open_ok
        self._block_on_read = block_on_read
        self._block_event = threading.Event()
        self._released = False
        self._entered_read = threading.Event()
        self.read_count = 0

    def isOpened(self):
        return self._open

    def read(self):
        self.read_count += 1
        if self._block_on_read and not self._released:
            self._entered_read.set()
            # Simulate a blocking network read – only unblocked by release()
            self._block_event.wait(timeout=30)
            return (False, None)
        if self._idx < len(self._frames):
            ret, frame = self._frames[self._idx]
            self._idx += 1
            return ret, frame
        return (False, None)

    def release(self):
        self._released = True
        self._block_event.set()  # unblock any pending read()

    def set(self, prop, val):
        pass  # accept CAP_PROP_BUFFERSIZE etc.

    def wait_until_read_entered(self, timeout=5):
        """Block the caller until ``read()`` has been entered at least once."""
        return self._entered_read.wait(timeout=timeout)


def _make_dummy_frame():
    """Return a small numpy array that looks like a BGR video frame."""
    import numpy as np
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Bug 1 – Stream interruption causes immediate exit (no reconnect)
# ---------------------------------------------------------------------------

class TestStreamReconnection:
    """The scanner should retry on transient stream failures."""

    def test_reconnects_after_transient_read_failure(self):
        """If cap.read() returns (False, None) once, the scanner should
        attempt to reopen the stream rather than exit immediately."""

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        status_msgs: list[str] = []
        errors: list[str] = []
        scanner.status_changed.connect(
            status_msgs.append, Qt.ConnectionType.DirectConnection
        )
        scanner.error_occurred.connect(
            errors.append, Qt.ConnectionType.DirectConnection
        )

        dummy = _make_dummy_frame()
        # First capture: a few good frames then a failure
        first_cap = FakeCapture(
            frames=[(True, dummy)] * 5 + [(False, None)],
            open_ok=True,
        )
        # Second capture (after reconnect): good frames then end
        second_cap = FakeCapture(
            frames=[(True, dummy)] * 10 + [(False, None)],
            open_ok=True,
        )
        # Third capture (for reconnect after second_cap exhausts)
        third_cap = FakeCapture(frames=[], open_ok=False)
        caps = iter([first_cap, second_cap, third_cap])

        with patch.object(
            scanner, "get_live_stream_info", return_value=_ok_stream_info()
        ):
            with patch.object(
                scanner, "_open_capture", side_effect=lambda url: next(caps)
            ):
                with patch.object(scanner, "_scan_frame", return_value=None):
                    with patch("utils.live_stream_scanner.time.sleep"):
                        scanner.start()
                        scanner.wait(5000)

        _process_events()

        assert second_cap.read_count > 0, (
            "Scanner did not reconnect after stream interruption"
        )
        reconnect_msgs = [
            m for m in status_msgs if "重连" in m or "reconnect" in m.lower()
        ]
        assert len(reconnect_msgs) > 0, (
            f"No reconnection status emitted. Status messages: {status_msgs}"
        )


# ---------------------------------------------------------------------------
# Bug 2 – stop() doesn't terminate when cap.read() blocks
# ---------------------------------------------------------------------------

class TestStopTermination:
    """stop() must actually terminate the scanner within a reasonable time,
    even when the underlying capture is blocking on a network read."""

    def test_stop_unblocks_hanging_read(self):
        fake_cap = FakeCapture(block_on_read=True, open_ok=True)

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        with patch.object(
            scanner, "get_live_stream_info", return_value=_ok_stream_info()
        ):
            with patch.object(scanner, "_open_capture", return_value=fake_cap):
                scanner.start()
                # Wait until the thread has entered the blocking read()
                entered = fake_cap.wait_until_read_entered(timeout=5)
                assert entered, "Thread never entered cap.read()"

                scanner.stop()
                finished = scanner.wait(2000)

        assert finished, (
            "Scanner thread did not terminate within 2 s after stop() – "
            "cap.read() is likely still blocking because stop() does not "
            "release the capture"
        )


# ---------------------------------------------------------------------------
# Bug 3 – Short QR codes silently dropped
# ---------------------------------------------------------------------------

class TestShortQRCodeHandling:
    """QR codes shorter than 24 characters must still be emitted."""

    def test_short_qr_code_is_emitted(self):
        dummy = _make_dummy_frame()
        short_qr = "KURO#SHORT"  # 10 chars, well under 24

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 10 + [(False, None)],
            open_ok=True,
        )

        with patch.object(
            scanner, "get_live_stream_info", return_value=_ok_stream_info()
        ):
            with patch.object(scanner, "_open_capture", return_value=fake_cap):
                with patch.object(scanner, "_scan_frame", return_value=short_qr):
                    scanner.start()
                    scanner.wait(5000)

        _process_events()

        assert short_qr in detected, (
            f"Short QR code ({short_qr!r}) was not emitted. "
            f"Detected codes: {detected}"
        )

    def test_long_qr_code_still_works(self):
        dummy = _make_dummy_frame()
        long_qr = "https://example.com/G152#KURO_ticket_abcdef123456"

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 10 + [(False, None)],
            open_ok=True,
        )

        with patch.object(
            scanner, "get_live_stream_info", return_value=_ok_stream_info()
        ):
            with patch.object(scanner, "_open_capture", return_value=fake_cap):
                with patch.object(scanner, "_scan_frame", return_value=long_qr):
                    scanner.start()
                    scanner.wait(5000)

        _process_events()

        assert long_qr in detected, (
            f"Long QR code was not emitted. Detected: {detected}"
        )

    def test_duplicate_short_qr_not_emitted_twice(self):
        """Even short codes must be de-duplicated."""
        dummy = _make_dummy_frame()
        short_qr = "KURO#SHORT"

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 30 + [(False, None)],
            open_ok=True,
        )

        with patch.object(
            scanner, "get_live_stream_info", return_value=_ok_stream_info()
        ):
            with patch.object(scanner, "_open_capture", return_value=fake_cap):
                with patch.object(scanner, "_scan_frame", return_value=short_qr):
                    scanner.start()
                    scanner.wait(5000)

        _process_events()

        assert detected.count(short_qr) == 1, (
            f"Short QR code emitted {detected.count(short_qr)} times, expected 1"
        )


# ---------------------------------------------------------------------------
# Fast frame decode + payload de-duplication
# ---------------------------------------------------------------------------

class TestFastFrameDecodeAndPayload:
    """Competitive live scanning path: decode BGR frames directly."""

    def test_scan_frame_uses_ai_array_fast_path(self):
        scanner = LiveStreamScanner()
        dummy = _make_dummy_frame()
        fake_ai = MagicMock()
        fake_ai.try_decode_array.return_value = "G152#KURO_FAST"

        fake_module = types.SimpleNamespace(ai_qr_scanner=fake_ai)
        with patch.dict(sys.modules, {"utils.ai_qr_scanner": fake_module}):
            result = scanner._scan_frame(dummy)

        assert result == "G152#KURO_FAST"
        fake_ai.try_decode_array.assert_called_once()
        _, kwargs = fake_ai.try_decode_array.call_args
        assert kwargs["color"] == "BGR"

    def test_same_ticket_with_different_url_is_emitted_once(self):
        dummy = _make_dummy_frame()
        ticket = "A" * 24
        first_qr = f"https://one.example/G152#KURO_{ticket}"
        second_qr = f"https://two.example/G152#KURO_{ticket}"

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 18 + [(False, None)],
            open_ok=True,
        )

        with patch.object(
            scanner, "get_live_stream_info", return_value=_ok_stream_info()
        ):
            with patch.object(scanner, "_open_capture", return_value=fake_cap):
                with patch.object(
                    scanner,
                    "_scan_frame",
                    side_effect=[first_qr, second_qr, second_qr, second_qr, second_qr, second_qr],
                ):
                    scanner.start()
                    scanner.wait(5000)

        _process_events()

        assert detected == [first_qr]

    def test_payload_helpers_extract_ticket_and_reject_noise(self):
        ticket = "B" * 24
        qr = f"https://example.com/G152#KURO_{ticket}"

        assert is_kuro_qr(qr) is True
        assert extract_kuro_ticket(qr) == ticket
        assert extract_kuro_ticket("https://example.com/not-a-login") is None


# ===========================================================================
# MHY_Scanner optimisation tests
# ===========================================================================

# ---------------------------------------------------------------------------
# 4 – LiveStreamInfo unified return type
# ---------------------------------------------------------------------------

class TestLiveStreamInfo:
    """LiveStreamInfo bundles status + url + headers in one object."""

    def test_normal_info_has_url_and_headers(self):
        info = LiveStreamInfo(
            status=LiveStreamStatus.Normal,
            url="http://example.com/live.flv",
            headers={"Referer": "https://live.bilibili.com"},
        )
        assert info.status == LiveStreamStatus.Normal
        assert info.url == "http://example.com/live.flv"
        assert info.headers["Referer"] == "https://live.bilibili.com"

    def test_error_info_defaults(self):
        info = LiveStreamInfo(status=LiveStreamStatus.Error)
        assert info.url == ""
        assert info.headers == {}

    def test_status_enum_values(self):
        assert int(LiveStreamStatus.Normal) == 0
        assert int(LiveStreamStatus.Absent) == 1
        assert int(LiveStreamStatus.NotLive) == 2
        assert int(LiveStreamStatus.Error) == 3


# ---------------------------------------------------------------------------
# 5 – Safe JSON parsing
# ---------------------------------------------------------------------------

class TestSafeJson:
    """_safe_json must never raise; returns None on bad input."""

    def test_valid_json(self):
        result = LiveStreamScanner._safe_json('{"code": 0}')
        assert result == {"code": 0}

    def test_empty_string(self):
        assert LiveStreamScanner._safe_json("") is None

    def test_malformed_json(self):
        assert LiveStreamScanner._safe_json("{invalid") is None

    def test_none_input(self):
        assert LiveStreamScanner._safe_json(None) is None

    def test_html_response(self):
        assert LiveStreamScanner._safe_json("<html>error</html>") is None


# ---------------------------------------------------------------------------
# 6 – Douyin pull_datas + live_core_sdk_data dual-path fallback
# ---------------------------------------------------------------------------

class TestDouyinStreamParsing:
    """_parse_douyin_stream should try pull_datas then live_core_sdk_data."""

    def _make_flv_stream_data(self, flv_url="http://pull.example.com/live.flv"):
        return json.dumps({
            "data": {"origin": {"main": {"flv": flv_url}}}
        })

    def test_pull_datas_path(self):
        """When pull_datas is present it should be preferred."""
        scanner = LiveStreamScanner()
        room_data = {
            "stream_url": {
                "pull_datas": {
                    "stream_0": {
                        "stream_data": self._make_flv_stream_data(
                            "http://pull.example.com/pull_datas.flv"
                        )
                    }
                },
                "live_core_sdk_data": {
                    "pull_data": {
                        "stream_data": self._make_flv_stream_data(
                            "http://pull.example.com/core_sdk.flv"
                        )
                    }
                },
            }
        }
        url = scanner._parse_douyin_stream(room_data)
        assert url == "http://pull.example.com/pull_datas.flv"

    def test_live_core_sdk_data_fallback(self):
        """When pull_datas is absent, fall back to live_core_sdk_data."""
        scanner = LiveStreamScanner()
        room_data = {
            "stream_url": {
                "live_core_sdk_data": {
                    "pull_data": {
                        "stream_data": self._make_flv_stream_data(
                            "http://pull.example.com/core_sdk.flv"
                        )
                    }
                }
            }
        }
        url = scanner._parse_douyin_stream(room_data)
        assert url == "http://pull.example.com/core_sdk.flv"

    def test_returns_empty_when_both_absent(self):
        scanner = LiveStreamScanner()
        room_data = {"stream_url": {}}
        assert scanner._parse_douyin_stream(room_data) == ""

    def test_handles_malformed_stream_data(self):
        scanner = LiveStreamScanner()
        room_data = {
            "stream_url": {
                "live_core_sdk_data": {
                    "pull_data": {"stream_data": "not-json"}
                }
            }
        }
        assert scanner._parse_douyin_stream(room_data) == ""


# ---------------------------------------------------------------------------
# 7 – FFmpeg low-latency parameters
# ---------------------------------------------------------------------------

class TestFFmpegLatencyParams:
    """_open_capture should set low-latency FFmpeg env vars."""

    def test_sets_ffmpeg_env_and_buffer_size(self):
        import cv2

        scanner = LiveStreamScanner()
        fake_cap = FakeCapture(open_ok=True)
        props_set: list = []
        fake_cap.set = lambda prop, val: props_set.append((prop, val))

        with patch("cv2.VideoCapture", return_value=fake_cap) as mock_vc:
            cap = scanner._open_capture("http://example.com/live.flv")

        # Environment variable should contain the low-latency options
        opts = os.environ.get("OPENCV_FFMPEG_CAPTURE_OPTIONS", "")
        assert "max_delay;0" in opts
        assert "probesize;1024" in opts
        assert "buffer_size;1000" in opts

        # CAP_PROP_BUFFERSIZE should have been set to 1
        assert (cv2.CAP_PROP_BUFFERSIZE, 1) in props_set


# ---------------------------------------------------------------------------
# 8 – Bilibili room_init error handling
# ---------------------------------------------------------------------------

class TestBilibiliStreamInfo:
    """_get_bilibili_stream_info handles HTTP and API errors gracefully."""

    def test_room_absent_code_60004(self):
        scanner = LiveStreamScanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({"code": 60004})

        with patch("requests.get", return_value=mock_resp):
            info = scanner._get_bilibili_stream_info("999999")

        assert info.status == LiveStreamStatus.Absent

    def test_room_not_live(self):
        scanner = LiveStreamScanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = json.dumps({
            "code": 0,
            "data": {"live_status": 0, "room_id": 12345},
        })

        with patch("requests.get", return_value=mock_resp):
            info = scanner._get_bilibili_stream_info("12345")

        assert info.status == LiveStreamStatus.NotLive

    def test_http_error_returns_error_status(self):
        scanner = LiveStreamScanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 500
        mock_resp.text = "Internal Server Error"

        with patch("requests.get", return_value=mock_resp):
            info = scanner._get_bilibili_stream_info("12345")

        assert info.status == LiveStreamStatus.Error

    def test_malformed_json_returns_error_status(self):
        scanner = LiveStreamScanner()
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "<html>not json</html>"

        with patch("requests.get", return_value=mock_resp):
            info = scanner._get_bilibili_stream_info("12345")

        assert info.status == LiveStreamStatus.Error


# ---------------------------------------------------------------------------
# 9 – Platform dispatch
# ---------------------------------------------------------------------------

class TestPlatformDispatch:
    """get_live_stream_info dispatches to the correct platform fetcher."""

    def test_unknown_platform_returns_error(self):
        scanner = LiveStreamScanner()
        info = scanner.get_live_stream_info("123", "huya")
        assert info.status == LiveStreamStatus.Error

    def test_bilibili_dispatch(self):
        scanner = LiveStreamScanner()
        expected = LiveStreamInfo(status=LiveStreamStatus.Normal, url="http://b.test")
        with patch.object(scanner, "_get_bilibili_stream_info", return_value=expected):
            info = scanner.get_live_stream_info("123", "bilibili")
        assert info is expected

    def test_douyin_dispatch(self):
        scanner = LiveStreamScanner()
        expected = LiveStreamInfo(status=LiveStreamStatus.Normal, url="http://d.test")
        with patch.object(scanner, "_get_douyin_stream_info", return_value=expected):
            info = scanner.get_live_stream_info("123", "douyin")
        assert info is expected


# ---------------------------------------------------------------------------
# 10 – run() emits correct errors for non-Normal status
# ---------------------------------------------------------------------------

class TestRunStatusErrors:
    """run() should emit the appropriate error for each LiveStreamStatus."""

    def test_absent_room_emits_error(self):
        scanner = LiveStreamScanner()
        scanner.set_stream_url("123", "bilibili")
        errors: list[str] = []
        scanner.error_occurred.connect(
            errors.append, Qt.ConnectionType.DirectConnection
        )

        with patch.object(
            scanner,
            "get_live_stream_info",
            return_value=LiveStreamInfo(status=LiveStreamStatus.Absent),
        ):
            scanner.start()
            scanner.wait(3000)

        _process_events()
        assert any("不存在" in e for e in errors)

    def test_not_live_emits_error(self):
        scanner = LiveStreamScanner()
        scanner.set_stream_url("123", "bilibili")
        errors: list[str] = []
        scanner.error_occurred.connect(
            errors.append, Qt.ConnectionType.DirectConnection
        )

        with patch.object(
            scanner,
            "get_live_stream_info",
            return_value=LiveStreamInfo(status=LiveStreamStatus.NotLive),
        ):
            scanner.start()
            scanner.wait(3000)

        _process_events()
        assert any("未开播" in e for e in errors)
