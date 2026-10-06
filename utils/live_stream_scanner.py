# -*- coding: utf-8 -*-
"""
直播流QR码扫描器（支持B站、抖音等平台）
使用OpenCV读取直播流，无需额外安装FFmpeg

Architecture:
- URL resolution lives in ``utils.platforms`` (one adapter per
  platform); this module only owns the capture → queue → decode
  pipeline plus the Qt thread plumbing.
- Importing ``LiveStreamInfo`` / ``LiveStreamStatus`` /
  ``DEFAULT_SCAN_FRAME_STRIDE`` from here keeps working (re-exported).

Performance design (v3.1):
- Capture and decode run on separate threads: the QThread pumps frames
  from the network while a dedicated decode worker consumes them from a
  bounded queue.  When decode can't keep up, the *oldest* queued frame is
  dropped so decode always works on fresh data (real-time over completeness).
- Scan cadence adapts automatically: an EWMA of decode latency raises the
  frame stride when decoding is expensive and keeps the configured stride
  when decoding is cheap.
"""
import cv2
import importlib
import math
import os
import queue
import sys
import threading
import time
from typing import Dict, Optional

import requests
from PySide6.QtCore import QThread, Signal

from utils import http as http_utils
from utils.log import get_logger
from utils.platforms import (
    BilibiliAdapter,
    DouyinAdapter,
    LiveStreamInfo,
    LiveStreamStatus,
)
from utils.platforms import douyin as douyin_module
from utils.qr_payload import extract_kuro_ticket


# Re-exported for backward compatibility (tests and ui import from here).
__all__ = [
    "LiveStreamScanner",
    "LiveStreamInfo",
    "LiveStreamStatus",
    "DEFAULT_SCAN_FRAME_STRIDE",
    "get_live_stream_scanner",
]


logger = get_logger("LiveStream")


# FFmpeg low-latency options applied when opening a stream.
# Ported from MHY_Scanner QRCodeForStream::setUrl().
_FFMPEG_LOW_LATENCY_OPTS = (
    "max_delay;0|"
    "probesize;1024|"
    "packetsize;128|"
    "rtbufsize;0|"
    "buffer_size;1000"
)

DEFAULT_SCAN_FRAME_STRIDE = 3

# Decode pipeline tuning
_MAX_SCAN_STRIDE = 30          # hard ceiling for the adaptive stride
_DECODE_JOIN_TIMEOUT = 5.0     # max seconds to wait for the decode thread
_EWMA_ALPHA = 0.25             # smoothing factor for decode-latency EWMA


# ----------------------------------------------------------------------
# Lazy optional-module resolution
# ----------------------------------------------------------------------
_module_cache: Dict[str, Optional[object]] = {}


def _get_optional_module(name: str):
    """Import *name* on first use and cache the result.

    The per-frame ``from utils.ai_qr_scanner import ...`` this replaces was
    pure overhead on the decode hot path (import machinery + ``sys.modules``
    lookup on every frame).  The module is still resolved through
    ``sys.modules`` first, so test hooks such as
    ``patch.dict(sys.modules, {"utils.ai_qr_scanner": fake})`` keep working.

    Raises:
        ImportError: if the module cannot be imported (cached after the
        first failure so we don't pay the import cost on every frame).
    """
    module = sys.modules.get(name)
    if module is not None:
        return module
    if name in _module_cache:
        cached = _module_cache[name]
        if cached is not None:
            return cached
        raise ImportError("optional module %s is unavailable" % name)
    try:
        module = importlib.import_module(name)
    except Exception as exc:
        _module_cache[name] = None
        raise ImportError("optional module %s is unavailable" % name) from exc
    _module_cache[name] = module
    return module


class LiveStreamScanner(QThread):
    """直播流扫描器（抓帧 → 有界队列 → 解码工作线程）"""

    # 信号
    qr_detected = Signal(str)  # 检测到QR码
    status_changed = Signal(str)  # 状态改变
    error_occurred = Signal(str)  # 错误发生

    # Reconnection settings
    MAX_RECONNECT_ATTEMPTS = 3
    RECONNECT_DELAYS = [0.6, 1.2, 2.0]

    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream_url: str = ""
        self.is_running: bool = False
        self.cap = None
        self._cap_lock = threading.Lock()
        self.platform: str = "bilibili"  # bilibili, douyin
        self.scan_frame_stride: int = self._load_scan_frame_stride()
        # Effective stride may grow at runtime when decoding is expensive.
        self._scan_stride: int = self.scan_frame_stride
        self._decode_ewma_ms: Optional[float] = None

        # Reuse one HTTP session for all platform API calls so TCP/TLS
        # connections are pooled instead of re-established per request,
        # and cookies (e.g. Douyin's ttwid) persist across calls.
        # NOTE: tests patch this attribute, so adapters are constructed
        # per call from ``self._session`` (see ``get_live_stream_info``).
        self._session: requests.Session = http_utils.new_session()

        # Decode pipeline: capture thread -> bounded queue -> decode worker.
        self._frame_queue: Optional[queue.Queue] = None
        self._decode_thread: Optional[threading.Thread] = None
        self._decode_stop = threading.Event()
        self._decode_queue_size: int = self._load_int_config(
            "live_decode_queue_size", 2, 1, 8
        )
        self._decode_budget_ms: float = self._load_float_config(
            "live_decode_budget_ms", 150.0, 20.0, 2000.0
        )
        self._last_ticket: str = ""

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _load_int_config(key: str, default: int, lo: int, hi: int) -> int:
        try:
            from utils.config_manager import config_manager
            value = int(config_manager.get(key, default))
        except Exception:
            value = default
        return max(lo, min(value, hi))

    @staticmethod
    def _load_float_config(key: str, default: float, lo: float, hi: float) -> float:
        try:
            from utils.config_manager import config_manager
            value = float(config_manager.get(key, default))
        except Exception:
            value = default
        return max(lo, min(value, hi))

    @classmethod
    def _load_scan_frame_stride(cls) -> int:
        """Load scan cadence from config and clamp it to a sensible range."""
        return cls._load_int_config(
            "live_scan_frame_stride", DEFAULT_SCAN_FRAME_STRIDE, 1, _MAX_SCAN_STRIDE
        )

    def set_stream_url(self, url: str, platform: str = "bilibili") -> None:
        """
        设置直播流地址

        Args:
            url: 直播流URL或房间号
            platform: 平台类型 (bilibili, douyin)
        """
        self.stream_url = url
        self.platform = platform

    # ------------------------------------------------------------------
    # Platform dispatch (thin facades over utils.platforms adapters)
    # ------------------------------------------------------------------

    def get_live_stream_info(self, room_id: str, platform: str) -> LiveStreamInfo:
        """Unified entry point – fetch stream info for *platform*.

        Returns a `LiveStreamInfo` with status, url, and any extra headers
        needed to open the stream.  Mirrors MHY_Scanner's
        ``GetLiveInfo<T>(roomID)`` template dispatch.
        """
        fetchers = {
            "bilibili": self._get_bilibili_stream_info,
            "douyin": self._get_douyin_stream_info,
        }
        fetcher = fetchers.get(platform)
        if fetcher is None:
            return LiveStreamInfo(status=LiveStreamStatus.Error)
        return fetcher(room_id)

    # -- Backward-compatible facades (kept for tests / external callers) --

    def _get_bilibili_stream_info(self, room_id: str) -> LiveStreamInfo:
        """Legacy entry point – delegates to :class:`BilibiliAdapter`."""
        return BilibiliAdapter(self._session).fetch(room_id)

    def _get_douyin_stream_info(self, room_id: str) -> LiveStreamInfo:
        """Legacy entry point – delegates to :class:`DouyinAdapter`."""
        return DouyinAdapter(self._session).fetch(room_id)

    @staticmethod
    def _parse_douyin_stream(room_data: dict) -> str:
        """Legacy entry point – delegates to ``platforms.douyin``."""
        return douyin_module.parse_stream_url(room_data)

    @staticmethod
    def _extract_flv_from_html(html: str) -> str:
        """Legacy entry point – delegates to ``platforms.douyin``."""
        return douyin_module.extract_flv_from_html(html)

    @staticmethod
    def _safe_json(text: object) -> Optional[dict]:
        """Legacy entry point – delegates to ``utils.http.safe_json``."""
        return http_utils.safe_json(text)

    # ------------------------------------------------------------------
    # Stream URL refresh / capture helpers
    # ------------------------------------------------------------------

    def _refresh_stream_url(self) -> str:
        """Re-fetch the stream URL before reconnecting.

        Stream URLs are short-lived; reconnecting with a stale URL fails
        even when the network is fine.  Returns "" when the refresh fails
        so the caller can fall back to the previous URL.
        """
        try:
            info = self.get_live_stream_info(self.stream_url, self.platform)
        except Exception as e:
            logger.warning("[LiveStream] Stream URL refresh failed: %s", e)
            return ""
        if info.status == LiveStreamStatus.Normal and info.url:
            return info.url
        return ""

    def _open_capture(self, url: str) -> cv2.VideoCapture:
        """Open a VideoCapture with low-latency FFmpeg options.

        Ported from MHY_Scanner ``QRCodeForStream::setUrl()`` which sets
        ``max_delay=0``, ``probesize=1024``, ``packetsize=128``, etc.
        In Python/OpenCV these are passed via the
        ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` environment variable.
        """
        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = _FFMPEG_LOW_LATENCY_OPTS
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        # Minimise internal frame buffer to reduce latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        return cap

    # ------------------------------------------------------------------
    # Capture / decode pipeline
    # ------------------------------------------------------------------

    def _release_cap(self) -> None:
        """Release the current capture exactly once (idempotent, thread-safe).

        ``stop()`` (UI thread), ``cleanup()`` and ``_try_reconnect()`` (scan
        thread) can all race here; the lock plus nulling the reference makes
        double-release impossible.
        """
        with self._cap_lock:
            cap, self.cap = self.cap, None
        if cap is not None:
            try:
                cap.release()
            except Exception:
                pass

    def _enqueue_frame(self, frame) -> None:
        """Hand a frame to the decode worker, dropping the oldest when full.

        Dropping the *oldest* (not the newest) keeps decode working on the
        freshest available frame – real-time over completeness.
        """
        q = self._frame_queue
        if q is None:
            return
        try:
            q.put_nowait(frame)
        except queue.Full:
            try:
                q.get_nowait()  # discard the stalest frame
            except queue.Empty:
                pass
            try:
                q.put_nowait(frame)
            except queue.Full:
                pass

    def _start_decode_worker(self) -> None:
        """Start the background decode worker (single consumer, FIFO)."""
        self._frame_queue = queue.Queue(maxsize=self._decode_queue_size)
        self._decode_stop.clear()
        self._decode_thread = threading.Thread(
            target=self._decode_loop, name="LiveStreamDecode", daemon=True
        )
        self._decode_thread.start()

    def _stop_decode_worker(self) -> None:
        """Signal the decode worker to exit and wait for it (bounded)."""
        thread = self._decode_thread
        if thread is None:
            return
        self._decode_thread = None
        self._decode_stop.set()
        q = self._frame_queue
        if q is not None:
            try:
                q.put_nowait(None)  # sentinel wakes a blocking get()
            except queue.Full:
                pass
        thread.join(timeout=_DECODE_JOIN_TIMEOUT)
        self._frame_queue = None

    def _decode_loop(self) -> None:
        """Decode worker: pull frames FIFO and run the QR decoder."""
        while not self._decode_stop.is_set():
            q = self._frame_queue
            if q is None:
                break
            try:
                frame = q.get(timeout=0.2)
            except queue.Empty:
                continue
            if frame is None:  # sentinel from _stop_decode_worker()
                break
            self._decode_frame(frame)

    def _decode_frame(self, frame) -> None:
        """Decode one frame, de-duplicate, and adapt the scan cadence."""
        started = time.perf_counter()
        try:
            qr_code = self._scan_frame(frame)
        except Exception as e:
            logger.warning("[LiveStream] Frame decode error: %s", e)
            return
        self._observe_decode_time((time.perf_counter() - started) * 1000.0)

        if not qr_code:
            return
        ticket = extract_kuro_ticket(qr_code)
        if not ticket:
            return
        if ticket == self._last_ticket:
            return
        self._last_ticket = ticket
        self.qr_detected.emit(qr_code)
        self.status_changed.emit("检测到QR码: %s..." % ticket[:8])

    def _observe_decode_time(self, dt_ms: float) -> None:
        """Track decode latency (EWMA) and adapt the scan stride.

        Why adaptive instead of a fixed stride: decode cost is dynamic –
        it depends on frame complexity (QR present? motion blur?) and on
        the machine. A fixed stride either wastes CPU on fast machines or
        lets the queue backlog grow on slow ones. The EWMA smooths out
        single-frame spikes so the stride doesn't jitter; the stride only
        ever grows (never below the configured value), so behaviour on a
        fast machine is identical to before.
        Assignment of a float is atomic under the GIL, so the capture
        thread can read ``_scan_stride`` lock-free.
        """
        prev = self._decode_ewma_ms
        self._decode_ewma_ms = (
            dt_ms if prev is None else prev + _EWMA_ALPHA * (dt_ms - prev)
        )
        budget = max(1.0, self._decode_budget_ms)
        needed = max(1, math.ceil(self._decode_ewma_ms / budget))
        self._scan_stride = max(
            self.scan_frame_stride, min(needed, _MAX_SCAN_STRIDE)
        )

    # ------------------------------------------------------------------
    # Main loop
    # ------------------------------------------------------------------

    def run(self) -> None:
        """主扫描循环（采集与解码分离，见模块 docstring）"""
        self.is_running = True
        self._last_ticket = ""
        self._scan_stride = self.scan_frame_stride
        self._decode_ewma_ms = None
        self.status_changed.emit("正在连接直播流...")

        # Fetch stream info via unified API
        room_id = self.stream_url
        info = self.get_live_stream_info(room_id, self.platform)

        if info.status == LiveStreamStatus.Absent:
            self.error_occurred.emit(info.detail or "房间不存在")
            self.is_running = False
            return
        if info.status == LiveStreamStatus.NotLive:
            self.error_occurred.emit(info.detail or "主播未开播")
            self.is_running = False
            return
        if info.status != LiveStreamStatus.Normal or not info.url:
            self.error_occurred.emit(info.detail or "无法获取直播流地址")
            self.is_running = False
            return

        stream_url = info.url

        # 打开视频流
        try:
            self.cap = self._open_capture(stream_url)
            if not self.is_running:
                # stop() was called while the capture was opening
                self._release_cap()
                return

            if not self.cap.isOpened():
                self.error_occurred.emit("无法打开直播流")
                self.is_running = False
                return

            self.status_changed.emit("已连接直播流，开始扫描...")
            self._start_decode_worker()
            try:
                frame_count = 0
                while self.is_running:
                    with self._cap_lock:
                        cap = self.cap
                    if cap is None:
                        break
                    ret, frame = cap.read()

                    if not ret:
                        # Attempt reconnection with exponential backoff
                        if not self._try_reconnect(stream_url):
                            self.error_occurred.emit("直播流中断，重连失败")
                            break
                        continue

                    frame_count += 1

                    # Scan cadence: fixed base stride, automatically raised
                    # when decoding is expensive (see _observe_decode_time).
                    if frame_count % self._scan_stride != 0:
                        continue

                    self._enqueue_frame(frame)
            finally:
                self._stop_decode_worker()

        except Exception as e:
            self.error_occurred.emit("扫描错误: %s" % e)
        finally:
            self.cleanup()

    def _try_reconnect(self, stream_url: str) -> bool:
        """Attempt to reconnect to the stream with exponential backoff.

        The stream URL is refreshed first: Bilibili/Douyin URLs expire, so
        retrying the stale URL would fail even on a healthy network.

        Returns True if reconnection succeeds, False if all attempts fail.
        """
        if not self.is_running:
            return False
        url = self._refresh_stream_url() or stream_url
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            if not self.is_running:
                return False
            if attempt < len(self.RECONNECT_DELAYS):
                delay = self.RECONNECT_DELAYS[attempt]
            else:
                delay = self.RECONNECT_DELAYS[-1]
            self.status_changed.emit(
                "直播流中断，正在重连 (%d/%d)..."
                % (attempt + 1, self.MAX_RECONNECT_ATTEMPTS)
            )
            time.sleep(delay)
            if not self.is_running:
                return False
            # Release old capture before reopening
            self._release_cap()
            cap = self._open_capture(url)
            if not self.is_running:
                # Stopped while (re)opening – don't leak the new capture.
                try:
                    cap.release()
                except Exception:
                    pass
                return False
            with self._cap_lock:
                self.cap = cap
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    self.status_changed.emit("重连成功，继续扫描...")
                    return True
        return False

    def _scan_frame(self, image) -> Optional[str]:
        """扫描单帧图像（统一解码契约 ``decode(image) -> str | None``）。"""
        try:
            ai_module = _get_optional_module("utils.ai_qr_scanner")
            return ai_module.ai_qr_scanner.decode(image)
        except Exception as e:
            try:
                qr_module = _get_optional_module("utils.qr_scanner")
                return qr_module.qr_scanner.decode(image)
            except Exception:
                logger.warning("[LiveStream] Scan error: %s", e)
                return None

    def stop(self) -> None:
        """停止扫描（线程安全：释放 capture 以解阻塞 cap.read()）"""
        self.is_running = False
        # Release the capture to unblock any pending cap.read()
        self._release_cap()
        self.status_changed.emit("正在停止...")

    def cleanup(self) -> None:
        """清理资源（幂等：可与 stop() 任意顺序调用）"""
        self._release_cap()
        self.is_running = False
        self.status_changed.emit("已停止")


# 全局实例
_live_stream_scanner = None
_live_stream_scanner_lock = threading.Lock()


def get_live_stream_scanner() -> LiveStreamScanner:
    """获取直播流扫描器单例（线程安全）"""
    global _live_stream_scanner
    if _live_stream_scanner is None:
        with _live_stream_scanner_lock:
            if _live_stream_scanner is None:
                _live_stream_scanner = LiveStreamScanner()
    return _live_stream_scanner
