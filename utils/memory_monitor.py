# -*- coding: utf-8 -*-
"""
长时内存监控：7×24 挂机场景的泄漏预警。

- 后台线程，每 5 分钟采样一次 RSS
- 内存持续增长超阈值 → 日志告警
- 提供 get_stats() 供 UI/悬浮窗展示
"""
import threading
import time
from typing import Optional, Dict

from utils.log import get_logger

logger = get_logger("Memory")


class MemoryMonitor:
    def __init__(self, warn_mb: float = 800.0, check_interval_s: float = 300.0):
        self.warn_mb = warn_mb
        self.check_interval_s = check_interval_s
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._samples: list = []  # (timestamp, rss_mb)
        self._lock = threading.Lock()
        self._warned = False

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._monitor, daemon=True,
                                        name="MemoryMonitor")
        self._thread.start()
        logger.info("[Memory] Monitor started")

    def stop(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2.0)

    def _get_rss_mb(self) -> float:
        try:
            import psutil
            return psutil.Process().memory_info().rss / 1024 / 1024
        except ImportError:
            # 无 psutil 时用 resource（Linux）或返回 0
            try:
                import resource
                return resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024
            except Exception:
                return 0.0
        except Exception:
            return 0.0

    def _monitor(self) -> None:
        while not self._stop.wait(self.check_interval_s):
            try:
                rss = self._get_rss_mb()
                if rss <= 0:
                    continue
                # 优化55：空闲时 gc——内存高时主动回收一代垃圾
                if rss > self.warn_mb * 0.8:
                    try:
                        import gc as _gc
                        _gc.collect(1)
                    except Exception:
                        pass
                with self._lock:
                    self._samples.append((time.time(), rss))
                    # 只保留最近 24 小时（288 个采样）
                    if len(self._samples) > 288:
                        self._samples.pop(0)
                    # 泄漏检测：最近 1 小时增长超 200MB
                    if len(self._samples) >= 12:
                        old = self._samples[-12][1]
                        growth = rss - old
                        if growth > 200 and not self._warned:
                            logger.warning(
                                f"[Memory] Possible leak: +{growth:.0f}MB in 1h "
                                f"(now {rss:.0f}MB)"
                            )
                            self._warned = True
                        elif growth < 50:
                            self._warned = False
                    # 绝对阈值告警
                    if rss > self.warn_mb and not self._warned:
                        logger.warning(f"[Memory] High usage: {rss:.0f}MB (warn at {self.warn_mb}MB)")
            except Exception:
                pass

    def get_stats(self) -> Dict[str, float]:
        with self._lock:
            if not self._samples:
                return {"rss_mb": 0.0, "samples": 0}
            latest = self._samples[-1][1]
            return {"rss_mb": latest, "samples": len(self._samples)}


# 全局单例
memory_monitor = MemoryMonitor()
