# -*- coding: utf-8 -*-
"""抢码战绩统计：二维码检出 -> 登录完成的端到端统计。

与 performance_monitor（截图/解码微观耗时）不同，这里只关心
抢码业务指标：抢了几次、成了几次、多快。
线程安全：用锁保护，ScanThread（工作线程）和 UI 线程都会写。
"""
import threading
import time
from typing import Dict, List, Optional


class GrabStats:
    """单例：记录每次抢码的时间线。"""

    _instance = None
    _lock = threading.Lock()

    def __new__(cls):
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
                    cls._instance._init()
        return cls._instance

    def _init(self):
        self._mu = threading.Lock()
        self._pending_detect_ts: Optional[float] = None  # 最近一次检出的时间
        self._records: List[Dict] = []  # [{detected_ts, login_ts, success, elapsed_ms}]
        self._max_records = 200

    def record_detected(self):
        """检出二维码（抢码开始）。"""
        with self._mu:
            self._pending_detect_ts = time.monotonic()

    def record_login_result(self, success: bool):
        """登录完成（成功/失败）。"""
        now = time.monotonic()
        with self._mu:
            if self._pending_detect_ts is None:
                return
            elapsed_ms = (now - self._pending_detect_ts) * 1000.0
            self._records.append({
                "success": success,
                "elapsed_ms": elapsed_ms,
            })
            if len(self._records) > self._max_records:
                self._records.pop(0)
            self._pending_detect_ts = None

    def summary(self) -> Dict:
        """汇总统计。"""
        with self._mu:
            records = list(self._records)
        total = len(records)
        succ = [r for r in records if r["success"]]
        elapsed = [r["elapsed_ms"] for r in succ]
        return {
            "total": total,
            "success": len(succ),
            "failed": total - len(succ),
            "success_rate": (len(succ) / total * 100.0) if total else 0.0,
            "avg_ms": (sum(elapsed) / len(elapsed)) if elapsed else 0.0,
            "fastest_ms": min(elapsed) if elapsed else 0.0,
            "slowest_ms": max(elapsed) if elapsed else 0.0,
        }

    def reset(self):
        with self._mu:
            self._records.clear()
            self._pending_detect_ts = None


grab_stats = GrabStats()
