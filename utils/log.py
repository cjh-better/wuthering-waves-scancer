# -*- coding: utf-8 -*-
"""Central logging setup for wuthering-waves-scancer.

Replaces ad-hoc ``print()`` calls with the standard :mod:`logging` module so
log output can be filtered, redirected, or silenced by the caller.

Console output is intentionally kept identical to the old ``print()`` style:
messages are written to stdout as plain text (existing ``[Tag] ...``
prefixes are preserved in the message itself).
"""
from __future__ import annotations

import logging
import sys

_configured = False


class _DedupFilter(logging.Filter):
    """优化83：同一错误 1 分钟内只输出一次（防刷屏）。"""
    def __init__(self):
        super().__init__()
        self._last: dict = {}
        import threading as _th
        self._lock = _th.Lock()

    def filter(self, record: logging.LogRecord) -> bool:
        # 只对 WARNING 及以上去重，INFO 正常输出
        if record.levelno < logging.WARNING:
            return True
        key = (record.name, record.levelno, record.getMessage()[:100])
        import time as _t
        now = _t.time()
        with self._lock:
            last = self._last.get(key, 0)
            if now - last < 60:
                return False
            self._last[key] = now
            # 定期清理旧 key
            if len(self._last) > 500:
                self._last = {k: v for k, v in self._last.items() if now - v < 60}
        return True


def _configure() -> None:
    """Install a single stdout handler once per process (idempotent)."""
    global _configured
    if _configured:
        return
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(logging.Formatter("%(message)s"))
    handler.addFilter(_DedupFilter())
    root = logging.getLogger("wws")
    root.addHandler(handler)
    root.setLevel(logging.INFO)
    # Don't propagate to the real root logger: the app never configured one,
    # and we don't want duplicate lines if an embedder did.
    root.propagate = False
    # 日志轮转：文件日志 10MB×5，避免 7×24 挂机日志无限增长
    try:
        import os
        from logging.handlers import RotatingFileHandler
        log_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "logs")
        os.makedirs(log_dir, exist_ok=True)
        log_path = os.path.join(log_dir, "app.log")
        fh = RotatingFileHandler(log_path, maxBytes=10*1024*1024, backupCount=5,
                                 encoding="utf-8")
        fh.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s %(message)s"))
        root.addHandler(fh)
    except Exception:
        pass
    _configured = True


def get_logger(name: str) -> logging.Logger:
    """Return a child logger of the ``wws`` namespace (configures on first use)."""
    _configure()
    return logging.getLogger("wws.%s" % name)
