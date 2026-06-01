# -*- coding: utf-8 -*-
"""
直播流QR码扫描器（支持B站、抖音等平台）
使用OpenCV读取直播流，无需额外安装FFmpeg

Optimized based on MHY_Scanner architecture:
- Unified LiveStreamInfo return type (status + url + headers)
- Safe JSON parsing with HTTP error checking
- Douyin pull_datas + live_core_sdk_data dual-path fallback
- FFmpeg low-latency parameters for faster QR detection
"""
import cv2
import os
import re
import requests
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional, Callable
from PySide6.QtCore import QThread, Signal
import time

from utils.qr_payload import extract_kuro_ticket


class LiveStreamStatus(IntEnum):
    """Live stream status codes (mirrors MHY_Scanner LiveStreamStatus)."""
    Normal = 0
    Absent = 1
    NotLive = 2
    Error = 3


@dataclass
class LiveStreamInfo:
    """Bundled result of a live stream query (status + url + headers).

    Ported from MHY_Scanner's ``LiveStreamInfo`` struct so that callers
    get status and URL in a single call instead of two separate methods.
    """
    status: LiveStreamStatus
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)


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


class LiveStreamScanner(QThread):
    """直播流扫描器"""
    
    # 信号
    qr_detected = Signal(str)  # 检测到QR码
    status_changed = Signal(str)  # 状态改变
    error_occurred = Signal(str)  # 错误发生
    
    # Reconnection settings
    MAX_RECONNECT_ATTEMPTS = 3
    RECONNECT_DELAYS = [0.6, 1.2, 2.0]
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.stream_url = ""
        self.is_running = False
        self.cap = None
        self.platform = "bilibili"  # bilibili, douyin
        self.scan_frame_stride = self._load_scan_frame_stride()

    @staticmethod
    def _load_scan_frame_stride() -> int:
        """Load scan cadence from config and clamp it to a sensible range."""
        try:
            from utils.config_manager import config_manager
            stride = int(config_manager.get("live_scan_frame_stride", DEFAULT_SCAN_FRAME_STRIDE))
        except Exception:
            stride = DEFAULT_SCAN_FRAME_STRIDE
        return max(1, min(stride, 30))
    
    def set_stream_url(self, url: str, platform: str = "bilibili"):
        """
        设置直播流地址
        
        Args:
            url: 直播流URL或房间号
            platform: 平台类型 (bilibili, douyin)
        """
        self.stream_url = url
        self.platform = platform
    
    # ------------------------------------------------------------------
    # Platform stream fetchers
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

    # -- Bilibili -------------------------------------------------------

    def _get_bilibili_stream_info(self, room_id: str) -> LiveStreamInfo:
        """Fetch Bilibili stream info.

        Uses the ``room_init`` API to resolve the real room ID, then
        ``getRoomPlayInfo`` (v2) to obtain the stream URL.  HTTP errors
        and malformed JSON are handled defensively (ported from
        MHY_Scanner ``LiveBili::GetLiveStreamInfo``).
        """
        try:
            # Step 1 – room_init (get real room ID + live status)
            init_url = "https://api.live.bilibili.com/room/v1/Room/room_init"
            r = requests.get(init_url, params={"id": room_id}, timeout=5)
            if r.status_code != 200:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            room_info = self._safe_json(r.text)
            if room_info is None:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            code = room_info.get("code")
            if code == 60004:
                return LiveStreamInfo(status=LiveStreamStatus.Absent)
            if code != 0:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            live_status = room_info["data"]["live_status"]
            if live_status != 1:
                return LiveStreamInfo(status=LiveStreamStatus.NotLive)

            real_room_id = room_info["data"]["room_id"]

            # Step 2 – getRoomPlayInfo (v2)
            play_url = "https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo"
            params = {
                "room_id": real_room_id,
                "protocol": "0,1",
                "format": "0,2",
                "codec": "0",
                "only_audio": "0",
                "only_video": "0",
                "qn": "10000",
            }
            r = requests.get(play_url, params=params, timeout=5)
            if r.status_code != 200:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            play_info = self._safe_json(r.text)
            if play_info is None:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            stream_url = self._parse_bilibili_play_info(play_info)
            if not stream_url:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/110.0.0.0 Safari/537.36 Edg/110.0.1587.41"
                ),
                "Referer": "https://live.bilibili.com",
            }
            return LiveStreamInfo(
                status=LiveStreamStatus.Normal,
                url=stream_url,
                headers=headers,
            )
        except Exception as e:
            print(f"[LiveStream] Bilibili fetch error: {e}")
            return LiveStreamInfo(status=LiveStreamStatus.Error)

    @staticmethod
    def _parse_bilibili_play_info(play_info: dict) -> str:
        """Extract the first stream URL from ``getRoomPlayInfo`` response."""
        try:
            streams = play_info["data"]["playurl_info"]["playurl"]["stream"]
            codec = streams[0]["format"][0]["codec"][0]
            host = codec["url_info"][0]["host"]
            base = codec["base_url"]
            extra = codec["url_info"][0]["extra"]
            return f"{host}{base}{extra}"
        except (KeyError, IndexError, TypeError):
            return ""

    # -- Douyin ---------------------------------------------------------

    def _get_douyin_stream_info(self, room_id: str) -> LiveStreamInfo:
        """Fetch Douyin stream info.

        Implements the full Douyin room API with both ``pull_datas`` and
        ``live_core_sdk_data`` fallback paths, ported from MHY_Scanner's
        ``LiveDouyin::GetLiveStreamInfo`` + ``GetStreamLinkFromResponse``.
        """
        try:
            user_agent = (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/92.0.4515.159 Safari/537.36"
            )
            headers = {
                "User-Agent": user_agent,
                "Referer": "https://live.douyin.com/",
            }
            params = (
                "aid=6383&app_name=douyin_web&live_id=1"
                "&device_platform=web&browser_language=zh-CN"
                "&browser_platform=Win32&browser_name=Edge"
                "&browser_version=139.0.0.0"
                "&is_need_double_stream=false"
                f"&web_rid={room_id}"
            )
            url = f"https://live.douyin.com/webcast/room/web/enter/?{params}"

            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code != 200:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            info = self._safe_json(r.text)
            if info is None:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            if info.get("status_code") != 0:
                return LiveStreamInfo(status=LiveStreamStatus.Absent)

            data_arr = info.get("data", {}).get("data", [])
            if not data_arr:
                return LiveStreamInfo(status=LiveStreamStatus.Absent)

            room_data = data_arr[0]
            status = room_data.get("status")
            if status == 4:
                return LiveStreamInfo(status=LiveStreamStatus.NotLive)
            if status != 2:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            # Extract FLV URL (try pull_datas first, then live_core_sdk_data)
            flv_url = self._parse_douyin_stream(room_data)
            if not flv_url:
                return LiveStreamInfo(status=LiveStreamStatus.Error)

            return LiveStreamInfo(
                status=LiveStreamStatus.Normal,
                url=flv_url,
            )
        except Exception as e:
            print(f"[LiveStream] Douyin fetch error: {e}")
            return LiveStreamInfo(status=LiveStreamStatus.Error)

    def _parse_douyin_stream(self, room_data: dict) -> str:
        """Extract FLV URL from Douyin room data.

        Tries ``pull_datas`` first, then falls back to
        ``live_core_sdk_data``.  This dual-path approach is ported from
        MHY_Scanner's ``LiveDouyin::GetStreamLinkFromResponse`` and
        fixes a missing fallback in the original KuRo_Scanner.
        """
        stream_url = room_data.get("stream_url", {})

        # Path 1: pull_datas (newer API)
        pull_datas = stream_url.get("pull_datas")
        if pull_datas and isinstance(pull_datas, dict):
            try:
                first_entry = next(iter(pull_datas.values()))
                stream_data_str = first_entry.get("stream_data", "")
                if stream_data_str:
                    sd = self._safe_json(stream_data_str)
                    if sd:
                        url = sd["data"]["origin"]["main"]["flv"]
                        if url:
                            return url
            except (KeyError, StopIteration, TypeError):
                pass

        # Path 2: live_core_sdk_data (older API)
        core_sdk = stream_url.get("live_core_sdk_data", {})
        pull_data = core_sdk.get("pull_data", {})
        stream_data_str = pull_data.get("stream_data", "")
        if not isinstance(stream_data_str, str) or not stream_data_str:
            return ""
        try:
            sd = self._safe_json(stream_data_str)
            if sd:
                return sd["data"]["origin"]["main"]["flv"]
        except (KeyError, TypeError):
            pass

        return ""

    # -- Helpers --------------------------------------------------------

    @staticmethod
    def _safe_json(text: str) -> Optional[dict]:
        """Parse JSON defensively, returning *None* on failure.

        Equivalent to MHY_Scanner's ``json::parse(text, nullptr, false)``
        + ``is_discarded()`` check.
        """
        try:
            return requests.compat.json.loads(text)  # type: ignore[attr-defined]
        except (ValueError, TypeError):
            return None
    
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

    def run(self):
        """主扫描循环"""
        self.is_running = True
        self.status_changed.emit("正在连接直播流...")
        
        # Fetch stream info via unified API
        room_id = self.stream_url
        info = self.get_live_stream_info(room_id, self.platform)

        if info.status == LiveStreamStatus.Absent:
            self.error_occurred.emit("房间不存在")
            self.is_running = False
            return
        if info.status == LiveStreamStatus.NotLive:
            self.error_occurred.emit("主播未开播")
            self.is_running = False
            return
        if info.status != LiveStreamStatus.Normal or not info.url:
            self.error_occurred.emit("无法获取直播流地址")
            self.is_running = False
            return

        stream_url = info.url

        # 打开视频流
        try:
            self.cap = self._open_capture(stream_url)
            
            if not self.cap.isOpened():
                self.error_occurred.emit("无法打开直播流")
                self.is_running = False
                return
            
            self.status_changed.emit("已连接直播流，开始扫描...")
            
            scan_stride = self.scan_frame_stride
            frame_count = 0
            last_ticket = ""
            
            while self.is_running:
                ret, frame = self.cap.read()
                
                if not ret:
                    # Attempt reconnection with exponential backoff
                    if not self._try_reconnect(stream_url):
                        self.error_occurred.emit("直播流中断，重连失败")
                        break
                    continue
                
                frame_count += 1
                
                # Scan a configurable cadence. Default 3 is closer to the C++
                # competitors without saturating Python CPU on weaker machines.
                if frame_count % scan_stride != 0:
                    continue
                
                try:
                    qr_code = self._scan_frame(frame)
                    
                    if qr_code:
                        ticket = extract_kuro_ticket(qr_code)
                        if not ticket:
                            continue
                        if ticket != last_ticket:
                            last_ticket = ticket
                            self.qr_detected.emit(qr_code)
                            self.status_changed.emit(f"检测到QR码: {ticket[:8]}...")
                
                except Exception as e:
                    print(f"[LiveStream] Frame scan error: {e}")
                    continue
                
                # 控制扫描速度
                time.sleep(0.02)
            
        except Exception as e:
            self.error_occurred.emit(f"扫描错误: {e}")
        finally:
            self.cleanup()
    
    def _try_reconnect(self, stream_url: str) -> bool:
        """Attempt to reconnect to the stream with exponential backoff.
        
        Returns True if reconnection succeeds, False if all attempts fail.
        """
        for attempt in range(self.MAX_RECONNECT_ATTEMPTS):
            if not self.is_running:
                return False
            delay = self.RECONNECT_DELAYS[attempt] if attempt < len(self.RECONNECT_DELAYS) else self.RECONNECT_DELAYS[-1]
            self.status_changed.emit(
                f"直播流中断，正在重连 ({attempt + 1}/{self.MAX_RECONNECT_ATTEMPTS})..."
            )
            time.sleep(delay)
            if not self.is_running:
                return False
            # Release old capture before reopening
            if self.cap:
                self.cap.release()
            self.cap = self._open_capture(stream_url)
            if self.cap.isOpened():
                ret, _ = self.cap.read()
                if ret:
                    self.status_changed.emit("重连成功，继续扫描...")
                    return True
        return False
    
    def _scan_frame(self, image) -> Optional[str]:
        """扫描单帧图像"""
        try:
            from utils.ai_qr_scanner import ai_qr_scanner

            if hasattr(ai_qr_scanner, "try_decode_array") and hasattr(image, "shape"):
                return ai_qr_scanner.try_decode_array(image, color="BGR")
            return ai_qr_scanner.try_decode_qr(image)
        except Exception as e:
            try:
                from PIL import Image
                from utils.qr_scanner import qr_scanner

                if hasattr(image, "shape"):
                    rgb_frame = cv2.cvtColor(image, cv2.COLOR_BGR2RGB)
                    image = Image.fromarray(rgb_frame)
                return qr_scanner.try_decode_qr(image)
            except Exception:
                print(f"[LiveStream] Scan error: {e}")
                return None
    
    def stop(self):
        """停止扫描"""
        self.is_running = False
        # Release the capture to unblock any pending cap.read()
        if self.cap:
            self.cap.release()
        self.status_changed.emit("正在停止...")
    
    def cleanup(self):
        """清理资源"""
        if self.cap:
            self.cap.release()
            self.cap = None
        self.is_running = False
        self.status_changed.emit("已停止")


# 全局实例
_live_stream_scanner = None

def get_live_stream_scanner() -> LiveStreamScanner:
    """获取直播流扫描器单例"""
    global _live_stream_scanner
    if _live_stream_scanner is None:
        _live_stream_scanner = LiveStreamScanner()
    return _live_stream_scanner


