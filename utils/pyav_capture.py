# -*- coding: utf-8 -*-
"""
PyAV 直播流采集后端（可选，仿 C++ 直调 FFmpeg）。

相比 OpenCV VideoCapture 的优势：
- 直接控制 FFmpeg 参数（probesize、analyzeduration、hwaccel 等）
- 更低的封装开销，无 OpenCV 内部缓冲
- 更精细的错误分类（网络超时 vs 解码失败）

使用条件：
- pip install av
- config 设置 live_backend="pyav"（默认 "opencv"）

接口兼容 cv2.VideoCapture 的最小子集：isOpened() / read() / release()，
read() 返回 (ok, bgr_frame)。
"""
from typing import Optional, Tuple
import numpy as np

from utils.log import get_logger

logger = get_logger("PyAV")

try:
    import av
    AV_AVAILABLE = True
except ImportError:
    AV_AVAILABLE = False
    logger.info("[PyAV] av not installed (pip install av), backend unavailable")


class PyAVCapture:
    """Minimal cv2.VideoCapture-compatible wrapper around PyAV."""

    def __init__(self, url: str, ffmpeg_opts: Optional[dict] = None,
                 hw_decode: bool = False):
        self.url = url
        self.container = None
        self.video_stream = None
        self._opened = False

        if not AV_AVAILABLE:
            return

        try:
            options = dict(ffmpeg_opts or {})
            # 低延迟默认参数（对齐 OpenCV 路径的 _ffmpeg_opts）
            options.setdefault("probesize", "1024")
            options.setdefault("analyzeduration", "500000")
            options.setdefault("fflags", "nobuffer")
            options.setdefault("flags", "low_delay")

            self.container = av.open(url, options=options, timeout=8.0)
            # 找到第一个视频流
            for s in self.container.streams:
                if s.type == "video":
                    self.video_stream = s
                    break
            if self.video_stream is None:
                logger.warning("[PyAV] No video stream found")
                self.container.close()
                self.container = None
                return

            # 硬件解码（可选）
            if hw_decode:
                try:
                    # PyAV 的 hwaccel 通过 codec_context 选项设置
                    # 不同平台支持不同，这里尝试 d3d11va
                    self.video_stream.codec_context.options = {
                        "hwaccel": "d3d11va",
                    }
                    logger.info("[PyAV] HW decode requested (d3d11va)")
                except Exception as e:
                    logger.warning(f"[PyAV] HW decode setup failed: {e}")

            self._opened = True
            logger.info("[PyAV] Opened stream")
        except Exception as e:
            logger.warning(f"[PyAV] Open failed: {e}")
            self._opened = False

    def isOpened(self) -> bool:
        return self._opened and self.container is not None

    def read(self) -> Tuple[bool, Optional[np.ndarray]]:
        """读取一帧，返回 (ok, bgr_frame)。"""
        if not self.isOpened():
            return False, None
        try:
            # 只解码视频流，跳过音频/字幕包（省 CPU）
            for packet in self.container.demux(self.video_stream):
                for frame in packet.decode():
                    # 转为 BGR numpy（对齐 OpenCV 输出）
                    arr = frame.to_ndarray(format="bgr24")
                    return True, arr
            # 流结束
            return False, None
        except Exception as e:
            logger.warning(f"[PyAV] Read failed: {e}")
            return False, None

    def release(self) -> None:
        if self.container is not None:
            try:
                self.container.close()
            except Exception:
                pass
            self.container = None
        self._opened = False

    # 兼容 cv2.VideoCapture.set() 的空实现（调用方可能设置 BUFFERIZE）
    def set(self, prop: int, value: float) -> bool:
        return False

    def get(self, prop: int) -> float:
        return 0.0
