# -*- coding: utf-8 -*-
"""极便宜的帧变化检测器 —— 抢码场景的主要解码触发器。

为什么用差分做触发器（而不是固定步长）：
- 直播画面大部分时间是静态的；一次 WeChatQR 全帧解码约 10-20ms，
  而一次 64x36 灰度 absdiff 约 0.05ms（快 200-400 倍，实测见
  benchmarks/decode_bench.py）。
- 码出现 = 全局画面突变。实测：300px 二维码随机出现时变化分数
  约 12.5，静态帧基线为 0.00 —— 信噪比极高。
- 对抗手段天然适配：主播把码放大（变化更大）、码出现在随机位置
  （差分是全局的，不依赖位置先验）—— ROI 记忆在这种对抗下已作废，
  差分是性价比最高的路径。

使用方式：采集线程每帧调用 ``score(frame)``；分数 >= 阈值视为"突变"，
调用方应立即解码该帧（插队）；否则跳过，靠安全网兜底。
"""
from typing import Optional, Tuple

import numpy as np

from utils.log import get_logger


logger = get_logger("LiveStream")

try:
    import cv2
    _CV2_AVAILABLE = True
except ImportError:
    cv2 = None
    _CV2_AVAILABLE = False

_DEFAULT_SIZE: Tuple[int, int] = (64, 36)


class FrameChangeDetector:
    """Detect significant frame changes with a tiny grayscale diff.

    The detector keeps one downscaled grayscale copy of the previous
    frame (64x36 ≈ 2.3KB).  ``score()`` returns the mean absolute
    difference; the first frame returns ``inf`` so callers always
    decode it (no baseline yet).
    """

    def __init__(
        self,
        threshold: float = 2.5,
        size: Tuple[int, int] = _DEFAULT_SIZE,
    ) -> None:
        self.threshold = threshold
        self.size = size
        self._prev: Optional[np.ndarray] = None

    def reset(self) -> None:
        """Forget the previous frame (call on stream reconnect)."""
        self._prev = None

    def score(self, frame) -> float:
        """Return the change score of *frame* vs the previous frame.

        Never raises; returns 0.0 for unusable frames (they get skipped,
        the safety net still covers them).
        """
        try:
            if not _CV2_AVAILABLE:
                return 0.0
            arr = np.asarray(frame)
            if arr.size == 0 or 0 in arr.shape:
                return 0.0
            if arr.ndim == 3:
                # 帧可能是 BGR（直播流）或 RGB；差分只关心强度，跳过
                # 颜色转换的精确性，直接按 BGR 转灰度（快路径）。
                small = cv2.resize(arr, self.size, interpolation=cv2.INTER_NEAREST)
                gray = cv2.cvtColor(small, cv2.COLOR_BGR2GRAY)
            elif arr.ndim == 2:
                gray = cv2.resize(arr, self.size, interpolation=cv2.INTER_NEAREST)
            else:
                return 0.0

            prev = self._prev
            self._prev = gray
            if prev is None:
                return float("inf")  # 首帧：无基线，强制解码
            # 与 benchmarks/decode_bench.py 同口径（阈值据此调定）
            return float(np.mean(cv2.absdiff(prev, gray)))
        except Exception as e:
            logger.warning("[FrameDiff] score failed: %s", e)
            return 0.0

    def is_hot(self, frame) -> bool:
        """True when *frame* changed significantly vs the previous one."""
        return self.score(frame) >= self.threshold
