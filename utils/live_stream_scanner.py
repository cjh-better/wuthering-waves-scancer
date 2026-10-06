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
from utils.frame_diff import FrameChangeDetector
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
# 默认低延迟 FFmpeg 参数（从 MHY_Scanner 移植，已是激进值）。
# 可通过配置 live_ffmpeg_opts 覆盖；timeout 为连接 IO 超时（微秒），
# 防止服务器只建连不推流时 cap.open()/read() 无限挂起。
_FFMPEG_LOW_LATENCY_OPTS = (
    "max_delay;0|"
    "probesize;1024|"
    "analyzeduration;500000|"
    "packetsize;128|"
    "rtbufsize;0|"
    "buffer_size;1000|"
    "timeout;8000000"
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

    # 抢码场景的重连退避（快速路径失败后）：比旧值更激进，兼顾对服务器礼貌
    MAX_RECONNECT_ATTEMPTS = 3
    RECONNECT_FAST_DELAYS = [0.3, 0.8, 1.5]
    # 熔断慢轮询：突发重连失败后，不立即放弃，转入低频重试。
    # 对抢码场景，流恢复后必须还在看；30s 间隔对服务器很礼貌。
    # 可配置：live_reconnect_slow_interval（秒）、live_reconnect_slow_max（次，0=无限）
    RECONNECT_SLOW_INTERVAL = 30.0
    RECONNECT_SLOW_MAX = 20

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
        # 零延迟提交回调：主窗口注册后，auto_login 模式下解码线程直接调用，
        # 跳过 signal→UI 线程的往返（约 5-20ms）。回调必须线程安全。
        self._qr_fast_callback = None
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
        self._decode_generation = 0  # 看门狗重启代际（防老线程复活抢队列）
        self._degrade_on_reconnect = False  # 卡顿触发的清晰度降级标记
        # 抢码录像：环形 buffer 保存最近 N 帧，检出时落盘
        from collections import deque
        self._record_buffer: deque = deque(maxlen=60)
        self._record_after: int = 0  # 检出后还需保存的帧数
        self._record_dir: Optional[str] = None
        self._decode_queue_size: int = self._load_int_config(
            "live_decode_queue_size", 2, 1, 8
        )
        self._decode_budget_ms: float = self._load_float_config(
            "live_decode_budget_ms", 150.0, 20.0, 2000.0
        )
        self._last_ticket: str = ""
        self._last_ticket_ts: float = 0.0

        # 帧差分触发器（抢码主触发器）：画面突变才解码，静态帧跳过。
        # 差分约 0.05ms/帧，比一次 WeChatQR 解码（10-20ms）快 200-400 倍。
        # 对抗适配：码放大/随机位置都是全局突变，差分天然覆盖；ROI 记忆
        # 在随机位置对抗下已作废，不再使用。
        self._diff_enabled: bool = self._load_bool_config(
            "live_frame_diff_enabled", True
        )
        self._diff_threshold: float = self._load_float_config(
            "live_frame_diff_threshold", 2.5, 0.5, 50.0
        )
        self._safety_net_stride: int = self._load_int_config(
            "live_safety_net_stride", 30, 5, 300
        )
        self._frame_diff = FrameChangeDetector(threshold=self._diff_threshold)
        self._static_frames: int = 0

    # ------------------------------------------------------------------
    # Config helpers
    # ------------------------------------------------------------------

    def _save_grab_record_async(self, frames: list, ticket: str) -> None:
        """后台落盘抢码录像（不阻塞采集线程）。"""
        try:
            from utils.config_manager import config_manager as _cm4
            import os
            import shutil as _shutil
            from datetime import datetime
            import cv2

            record_dir = str(_cm4.get("grab_record_dir", "grab_records"))
            # 优化98：磁盘空间不足时停止录像并告警（<500MB）
            try:
                free_mb = _shutil.disk_usage(record_dir).free // (1024 * 1024)
                if free_mb < 500:
                    logger.warning(
                        "[Record] 磁盘空间不足 (%dMB)，跳过录像", free_mb
                    )
                    return
            except Exception:
                pass
            # 优化95：清理 7 天前的旧录像（防无限增长）
            try:
                import time as _t
                now = _t.time()
                for entry in os.listdir(record_dir):
                    p = os.path.join(record_dir, entry)
                    if os.path.isdir(p) and (now - os.path.getmtime(p)) > 7 * 86400:
                        _shutil.rmtree(p, ignore_errors=True)
            except Exception:
                pass
            os.makedirs(record_dir, exist_ok=True)
            ts = datetime.now().strftime("%Y%m%d_%H%M%S")
            subdir = os.path.join(record_dir, f"{ts}_{ticket[:12]}")
            os.makedirs(subdir, exist_ok=True)

            for i, frame in enumerate(frames):
                path = os.path.join(subdir, f"frame_{i:04d}.jpg")
                cv2.imwrite(path, frame, [cv2.IMWRITE_JPEG_QUALITY, 85])
            logger.info(f"[Record] Saved {len(frames)} frames to {subdir}")
        except Exception as e:
            logger.warning(f"[Record] Save failed: {e}")

    def _save_grab_record(self) -> None:
        """同步落盘（兼容旧调用，现已改走 _save_grab_record_async）。"""
        try:
            frames = list(self._record_buffer)
            ticket = getattr(self, "_record_ticket", "unknown")
            self._record_buffer.clear()
            self._save_grab_record_async(frames, ticket)
        except Exception:
            pass


    def set_qr_fast_callback(self, callback) -> None:
        """注册零延迟提交回调（线程安全，由解码线程直接调用）。"""
        self._qr_fast_callback = callback

    @staticmethod
    def _load_int_config(key: str, default: int, lo: int, hi: int) -> int:
        try:
            from utils.config_manager import config_manager
            value = int(config_manager.get(key, default))
        except Exception:
            value = default
        return max(lo, min(value, hi))

    @staticmethod
    def _load_bool_config(key: str, default: bool) -> bool:
        try:
            from utils.config_manager import config_manager
            value = config_manager.get(key, default)
            if isinstance(value, str):
                return value.strip().lower() in ("1", "true", "yes", "on")
            return bool(value)
        except Exception:
            return default

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

    @staticmethod
    def _ffmpeg_opts() -> str:
        """FFmpeg 拉流参数（可配置覆盖，非法值回退默认）。"""
        try:
            from utils.config_manager import config_manager
            opts = config_manager.get("live_ffmpeg_opts", "")
            if isinstance(opts, str) and opts.strip():
                base = opts.strip()
            else:
                base = _FFMPEG_LOW_LATENCY_OPTS
            # 代理支持：live_proxy 配置时追加 http_proxy 参数
            proxy = str(config_manager.get("live_proxy", "")).strip()
            if proxy:
                # FFmpeg http 协议支持 http_proxy 选项
                base += f";http_proxy;{proxy}"
            return base
        except Exception:
            pass
        return _FFMPEG_LOW_LATENCY_OPTS

    def _open_capture(self, url: str):
        """Open a VideoCapture with low-latency FFmpeg options.

        Ported from MHY_Scanner ``QRCodeForStream::setUrl()`` which sets
        ``max_delay=0``, ``probesize=1024``, ``packetsize=128``, etc.
        In Python/OpenCV these are passed via the
        ``OPENCV_FFMPEG_CAPTURE_OPTIONS`` environment variable.

        后端可选：live_backend="pyav" 时使用 PyAV（需 pip install av），
        否则用 OpenCV。返回的对象兼容 read()/release()/isOpened()。
        """
        from utils.config_manager import config_manager as _cm2
        backend = _cm2.get("live_backend", "opencv")
        hw = _cm2.get("live_hw_decode", False)

        if backend == "pyav":
            try:
                from utils.pyav_capture import PyAVCapture, AV_AVAILABLE
                if AV_AVAILABLE:
                    logger.info("[Live] Using PyAV backend")
                    # _ffmpeg_opts() 返回 env 字符串，转为 dict
                    opts = self._ffmpeg_opts_dict()
                    return PyAVCapture(url, ffmpeg_opts=opts, hw_decode=hw)
                else:
                    logger.warning("[PyAV] Not available, falling back to OpenCV")
            except Exception as e:
                logger.warning(f"[PyAV] Backend init failed: {e}, fallback to OpenCV")

        os.environ["OPENCV_FFMPEG_CAPTURE_OPTIONS"] = self._ffmpeg_opts()
        cap = cv2.VideoCapture(url, cv2.CAP_FFMPEG)
        # Minimise internal frame buffer to reduce latency
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        # 优化22：弱网时增大 buffer 防抖（默认 1 帧最低延迟，
        # live_buffer_size>1 时容忍抖动）
        try:
            from utils.config_manager import config_manager as _cm_buf
            buf_size = int(_cm_buf.get("live_buffer_size", 1))
            if buf_size > 1:
                cap.set(cv2.CAP_PROP_BUFFERSIZE, min(10, buf_size))
        except Exception:
            pass
        # 硬件解码（可选）：D3D11/DXVA2，省 CPU。默认关闭（兼容性参差，
        # 部分驱动会黑屏或更慢）。需 Windows + 兼容 GPU。
        try:
            if hw:
                ok = cap.set(cv2.CAP_PROP_HW_ACCELERATION, cv2.VIDEO_ACCELERATION_D3D11)
                # 回读确认（部分后端 set 返回 True 但实际未生效）
                actual = cap.get(cv2.CAP_PROP_HW_ACCELERATION)
                logger.info(f"[Live] HW decode requested (D3D11): set_ok={ok}, actual={actual}")
                if not ok:
                    logger.warning("[Live] HW decode NOT accepted by backend, using software decode")
        except Exception as e:
            logger.warning(f"[Live] HW decode setup failed: {e}")
        return cap

    def _ffmpeg_opts_dict(self) -> dict:
        """将 _ffmpeg_opts() 的 env 字符串解析为 dict（供 PyAV 用）。"""
        opts_str = self._ffmpeg_opts()
        result = {}
        # 格式为 "key;value;key;value..."，按分号切分后两两配对
        items = [p.strip() for p in opts_str.split(";") if p.strip()]
        for i in range(0, len(items) - 1, 2):
            result[items[i]] = items[i + 1]
        return result

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

    def _drain_queue(self) -> None:
        """Drop all queued (not-yet-decoded) frames.

        Used when a *hot* frame (significant change) arrives: stale frames
        queued ahead of it would only delay the decode that matters.
        Real-time over completeness, applied one level deeper.
        """
        q = self._frame_queue
        if q is None:
            return
        try:
            while True:
                q.get_nowait()
        except queue.Empty:
            pass

    def _enqueue_frame(self, frame) -> None:
        """Hand a frame to the decode worker, dropping the oldest when full.

        Dropping the *oldest* (not the newest) keeps decode working on the
        freshest available frame – real-time over completeness.
        """
        # 抢码录像：每帧都进环形 buffer（浅拷贝引用，不复制数据）
        try:
            from utils.config_manager import config_manager as _cm
            if _cm.get("grab_record_enabled", False):
                self._record_buffer.append(frame)
                # 检出后继续收 N 帧，然后落盘（后台线程，不阻塞采集）
                if self._record_after > 0:
                    self._record_after -= 1
                    if self._record_after == 0:
                        frames = list(self._record_buffer)
                        ticket = getattr(self, "_record_ticket", "unknown")
                        self._record_buffer.clear()
                        import threading as _th
                        _th.Thread(
                            target=self._save_grab_record_async,
                            args=(frames, ticket),
                            daemon=True, name="GrabRecordSave",
                        ).start()
        except Exception:
            pass
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
        # generation 计数器：看门狗重启时递增，老线程恢复后发现代际不符自杀，
        # 避免与新线程同时消费队列（native hang 后 join 超时的场景）
        self._decode_generation = getattr(self, "_decode_generation", 0) + 1
        gen = self._decode_generation
        self._decode_thread = threading.Thread(
            target=self._decode_loop, args=(gen,),
            name=f"LiveStreamDecode-g{gen}", daemon=True
        )
        self._decode_thread.start()
        # 启动看门狗：15s 无心跳则重启解码线程
        try:
            from utils.decode_watchdog import DecodeWatchdog
            self._watchdog = DecodeWatchdog(
                timeout_s=15.0, on_timeout=self._on_decode_hung
            )
            self._watchdog.start()
        except Exception:
            pass

    def _on_decode_hung(self) -> None:
        """看门狗回调：解码线程 hang，重启之。"""
        logger.warning("[Live] Decode worker hung, restarting...")
        try:
            self._stop_decode_worker()
        except Exception:
            pass
        try:
            self._start_decode_worker()
        except Exception as e:
            logger.warning(f"[Live] Decode worker restart failed: {e}")

    def _stop_decode_worker(self) -> None:
        """Signal the decode worker to exit and wait for it (bounded)."""
        thread = self._decode_thread
        if thread is None:
            return
        self._decode_thread = None
        self._decode_stop.set()
        # 停看门狗
        try:
            if getattr(self, "_watchdog", None):
                self._watchdog.stop()
                self._watchdog = None
        except Exception:
            pass
        q = self._frame_queue
        if q is not None:
            try:
                q.put_nowait(None)  # sentinel wakes a blocking get()
            except queue.Full:
                pass
        thread.join(timeout=_DECODE_JOIN_TIMEOUT)
        self._frame_queue = None

    def _decode_loop(self, generation: int) -> None:
        """Decode worker: pull frames FIFO and run the QR decoder.

        generation: 启动时的代际；看门狗重启后老线程若从 native hang 中
        恢复，发现代际不符立即退出，不与新线程抢队列。
        """
        while not self._decode_stop.is_set():
            # 代际检查：已是老一代，直接自杀
            if generation != getattr(self, "_decode_generation", generation):
                logger.info(f"[Live] Stale decode worker (gen {generation}) exiting")
                return
            # 看门狗心跳：每次循环都打，hang 住则触发重启
            try:
                if getattr(self, "_watchdog", None):
                    self._watchdog.heartbeat()
            except Exception:
                pass
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
            # pyzbar 兜底（~200ms）只在没有更新帧排队时跑：若有更新鲜的帧
            # 在等，慢兜底会队头阻塞它们；空闲时跑兜底是免费的。
            q = self._frame_queue
            allow_slow = q is None or q.empty()
            qr_code = self._scan_frame(frame, allow_slow_fallback=allow_slow)
        except Exception as e:
            logger.warning("[LiveStream] Frame decode error: %s", e)
            return
        self._observe_decode_time((time.perf_counter() - started) * 1000.0)

        if not qr_code:
            return
        ticket = extract_kuro_ticket(qr_code)
        if not ticket:
            return
        # 优化7：ticket 去重加 5 分钟时间窗口——同一 ticket 5 分钟后
        # 视为新的（二维码刷新了），避免永久去重导致漏码。
        import time as _t
        now = _t.time()
        if ticket == self._last_ticket and (now - self._last_ticket_ts) < 300:
            return
        self._last_ticket = ticket
        self._last_ticket_ts = now
        # 抢码录像：检出时触发，保存前 N 帧 + 后 N 帧
        try:
            from utils.config_manager import config_manager as _cm3
            if _cm3.get("grab_record_enabled", False):
                n = int(_cm3.get("grab_record_frames", 30))
                # 调整 buffer 大小为 2N（前 N 帧）
                if self._record_buffer.maxlen != n:
                    from collections import deque
                    self._record_buffer = deque(self._record_buffer, maxlen=n)
                self._record_after = n  # 后 N 帧
                self._record_ticket = ticket
        except Exception:
            pass
        # 零延迟提交：auto_login 时解码线程直接启动登录，不等 signal 往返
        if self._qr_fast_callback is not None:
            try:
                self._qr_fast_callback(qr_code, ticket)
            except Exception:
                pass
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
        self._last_ticket_ts = 0.0
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
            self._frame_diff.reset()
            self._static_frames = 0
            try:
                frame_count = 0
                # 卡顿检测：连续 10 秒读不到帧 → 置位降级标记，
                # _try_reconnect 中会降一档清晰度后重连
                last_frame_ts = time.time()
                STALL_SECONDS = 10.0
                while self.is_running:
                    with self._cap_lock:
                        cap = self.cap
                    if cap is None:
                        break
                    ret, frame = cap.read()

                    if not ret:
                        if time.time() - last_frame_ts > STALL_SECONDS:
                            logger.warning("[Live] %.0f 秒无帧，疑似卡顿", STALL_SECONDS)
                            self._degrade_on_reconnect = True
                        # Attempt reconnection with exponential backoff
                        if not self._try_reconnect(stream_url):
                            self.error_occurred.emit("直播流中断，多次重连失败，已停止")
                            break
                        self._frame_diff.reset()
                        self._static_frames = 0
                        last_frame_ts = time.time()
                        continue

                    frame_count += 1
                    last_frame_ts = time.time()

                    if self._diff_enabled:
                        # 主触发器：帧差分。突变帧插队（排空旧帧立即解码），
                        # 静态帧跳过，每 live_safety_net_stride 帧兜底一次。
                        # 差分约 0.05ms，固定步长在此模式下不再使用。
                        if self._frame_diff.is_hot(frame):
                            self._drain_queue()
                            self._enqueue_frame(frame)
                            self._static_frames = 0
                            # 投机预热：帧变热→二维码可能出现，提前建连
                            # （后台线程+30s冷却，不阻塞）
                            try:
                                from utils.kuro_api import kuro_api as _api
                                _api.speculative_warmup()
                            except Exception:
                                pass
                        else:
                            self._static_frames += 1
                            if self._static_frames >= self._safety_net_stride:
                                self._enqueue_frame(frame)
                                self._static_frames = 0
                        continue

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

    def _try_reopen(self, url: str) -> bool:
        """Try to (re)open *url* once, without any delay.

        Returns True when the stream yields a frame.  Never raises.
        """
        if not self.is_running:
            return False
        try:
            self._release_cap()
            cap = self._open_capture(url)
        except Exception:
            return False
        if not self.is_running:
            # Stopped while (re)opening – don't leak the new capture.
            try:
                cap.release()
            except Exception:
                pass
            return False
        with self._cap_lock:
            self.cap = cap
        try:
            if cap.isOpened():
                ret, _ = cap.read()
                if ret:
                    return True
        except Exception:
            pass
        return False

    def _reconnect_config(self):
        """熔断慢轮询的配置（秒，次）。"""
        interval = self._load_float_config(
            "live_reconnect_slow_interval", self.RECONNECT_SLOW_INTERVAL, 5.0, 300.0
        )
        max_tries = self._load_int_config(
            "live_reconnect_slow_max", self.RECONNECT_SLOW_MAX, 0, 1000
        )
        return interval, max_tries

    def _try_reconnect(self, stream_url: str) -> bool:
        """Reconnect in two phases: burst, then circuit-breaker slow polling.

        Phase 1 (burst): fast path first, then refresh + backoff.
        Why fast path first: most interruptions are transient blips where
        the current URL is still valid.  Trying the current URL immediately
        costs one ``cap.read()`` (~100-300ms) and wins in the common case.

        Phase 2 (circuit breaker): if the burst fails, don't give up –
        the QR may appear after recovery. Poll at a low frequency
        (default every 30s, up to 20 times) instead of hammering the
        server or abandoning the watch entirely.

        Returns True if reconnection succeeds, False if abandoned/stopped.
        """
        if not self.is_running:
            return False

        # Phase 1: burst.
        # Fast path: transient blip – the URL is probably still good.
        self.status_changed.emit("直播流中断，立即重试...")
        if self._try_reopen(stream_url):
            self._on_reconnected()
            return True

        # Slow path: the URL may have expired – refresh it, then back off.
        # (Bilibili/Douyin URLs are short-lived.)
        url = self._refresh_stream_url() or stream_url
        # 清晰度自动降级（item 4）：卡顿标记置位时，先降一档清晰度再刷新 URL。
        # douyin_module 已在模块顶层 import，避免方法内 import 的副作用。
        if self._degrade_on_reconnect and self.platform == "douyin":
            self._degrade_on_reconnect = False
            try:
                new_q = douyin_module.degrade_quality()
                if new_q:
                    logger.info("[Live] 卡顿触发清晰度降级 → %s，刷新流地址", new_q)
                    self.status_changed.emit(
                        "检测到卡顿，已降为 %s 清晰度重连..." % new_q
                    )
                    url = self._refresh_stream_url() or url
            except Exception as e:
                logger.warning("[Live] 清晰度降级失败: %s", e)
        delays = self.RECONNECT_FAST_DELAYS
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            if not self.is_running:
                return False
            delay = delays[attempt] if attempt < len(delays) else delays[-1]
            # 优化25：加 ±20% jitter，避免多实例同时重连打爆服务器
            import random as _rand
            delay = delay * (0.8 + 0.4 * _rand.random())
            self.status_changed.emit(
                "直播流中断，正在重连 (%d/%d)..."
                % (attempt + 1, self.MAX_RECONNECT_ATTEMPTS)
            )
            time.sleep(delay)
            if self._try_reopen(url):
                self._on_reconnected()
                return True

        # Phase 2: circuit breaker – low-frequency polling.
        interval, max_tries = self._reconnect_config()
        attempt = 0
        while self.is_running and (max_tries == 0 or attempt < max_tries):
            attempt += 1
            self.status_changed.emit(
                "直播流仍未恢复，%ds 后重试 (%d/%s)..."
                % (int(interval), attempt, "∞" if max_tries == 0 else max_tries)
            )
            # 可中断的 sleep：stop() 能立即打断，不用干等整个 interval
            if self._interruptible_sleep(interval):
                return False  # stopped during sleep
            url = self._refresh_stream_url() or url
            if self._try_reopen(url):
                self._on_reconnected()
                return True
        return False

    def _on_reconnected(self):
        """重连成功后的统一状态复位。"""
        self._frame_diff.reset()
        self._static_frames = 0
        self.status_changed.emit("重连成功，继续扫描...")

    def _interruptible_sleep(self, seconds: float) -> bool:
        """Sleep that wakes early when stopped. Returns True if stopped."""
        deadline = time.monotonic() + seconds
        while self.is_running:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                return False
            time.sleep(min(0.5, remaining))
        return True

    def _scan_frame(self, image, allow_slow_fallback: bool = True) -> Optional[str]:
        """扫描单帧图像（统一解码契约 ``decode(image) -> str | None``）。"""
        try:
            ai_module = _get_optional_module("utils.ai_qr_scanner")
            return ai_module.ai_qr_scanner.decode(
                image, allow_slow_fallback=allow_slow_fallback
            )
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
