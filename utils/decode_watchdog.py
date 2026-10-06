# -*- coding: utf-8 -*-
"""
解码看门狗：监控解码工作线程，hang 住自动重启。

- 被监控方需定期调用 heartbeat()
- 超过阈值无心跳 → 调用 on_timeout 回调（由调用方实现重启）
- 后台线程，不阻塞主流程
"""
import threading
import time
from typing import Callable, Optional

from utils.log import get_logger

logger = get_logger("Watchdog")


class DecodeWatchdog:
    def __init__(self, timeout_s: float = 15.0,
                 on_timeout: Optional[Callable[[], None]] = None):
        self.timeout_s = timeout_s
        self.on_timeout = on_timeout
        self._last_beat = time.time()
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._last_beat = time.time()
        self._thread = threading.Thread(target=self._watch, daemon=True,
                                        name="DecodeWatchdog")
        self._thread.start()
        logger.info(f"[Watchdog] Started (timeout={self.timeout_s}s)")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def heartbeat(self) -> None:
        """被监控线程定期调用，表示还活着。"""
        with self._lock:
            self._last_beat = time.time()

    def _watch(self) -> None:
        while not self._stop.wait(2.0):
            with self._lock:
                idle = time.time() - self._last_beat
            if idle > self.timeout_s:
                logger.warning(f"[Watchdog] Decode thread hung ({idle:.1f}s), triggering restart")
                try:
                    if self.on_timeout:
                        self.on_timeout()
                except Exception as e:
                    logger.warning(f"[Watchdog] on_timeout failed: {e}")
                # 重置心跳，避免重复触发（由 on_timeout 负责真正重启）
                with self._lock:
                    self._last_beat = time.time()
