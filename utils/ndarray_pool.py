# -*- coding: utf-8 -*-
"""
numpy buffer 复用池（截图/缩放中间 buffer）。

按 (shape, dtype) 缓存 array，避免每 tick 分配 6MB+ 内存。
线程安全（锁保护），LRU 淘汰（最多保留 8 个）。
"""
import threading
from collections import OrderedDict
from typing import Tuple

import numpy as np


class NDArrayPool:
    """numpy 数组对象池，按 (shape, dtype) 复用，避免高频分配。"""
    def __init__(self, max_cached: int = 8):
        self._cache: "OrderedDict[Tuple[tuple, str], np.ndarray]" = OrderedDict()
        self._lock = threading.Lock()
        self._max_cached = max_cached

    def get(self, shape: tuple, dtype=np.uint8) -> np.ndarray:
        """获取指定 shape/dtype 的 buffer（复用或新建）。"""
        key = (tuple(shape), np.dtype(dtype).name)
        with self._lock:
            if key in self._cache:
                arr = self._cache.pop(key)
                # 放到末尾（MRU）
                self._cache[key] = arr
                return arr
        return np.empty(shape, dtype=dtype)

    def put(self, arr: np.ndarray) -> None:
        """归还 buffer（调用方不再使用后）。"""
        if arr is None:
            return
        key = (tuple(arr.shape), arr.dtype.name)
        with self._lock:
            if key in self._cache:
                return
            self._cache[key] = arr
            # LRU 淘汰
            while len(self._cache) > self._max_cached:
                self._cache.popitem(last=False)

    def clear(self) -> None:
        """清空缓存的数组。"""
        with self._lock:
            self._cache.clear()


# 全局单例
ndarray_pool = NDArrayPool()

def _apply_pool_size():
    """优化19：pool 大小可配置（默认 12，覆盖常用尺寸）。"""
    try:
        from utils.config_manager import config_manager
        size = int(config_manager.get("ndarray_pool_size", 12))
        ndarray_pool._max_cached = max(4, min(32, size))
    except Exception:
        pass

_apply_pool_size()
