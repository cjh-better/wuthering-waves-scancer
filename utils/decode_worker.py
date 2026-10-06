# -*- coding: utf-8 -*-
"""
子进程隔离解码 worker（对应 issue #8 的终极防护）。

背景：WeChatQR 的 native 代码若 segfault，进程内无法捕获，
整个应用直接闪退。thread-local 已解决已知的并发 crash，
但 native 层的未知 bug 仍可能导致闪退。

本模块把解码放到独立子进程：
- 子进程 segfault → 只是 worker 死了，主进程检测到后重启它；
- 主进程（UI）永远不受影响。

使用方式（默认关闭，config ``decode_subprocess_isolation=true`` 开启）::

    from utils.decode_worker import IsolatedDecoder
    dec = IsolatedDecoder()
    ticket = dec.decode(bgr_numpy_array, timeout=10.0)  # str | None
    dec.shutdown()

Windows 注意：multiprocessing 用 spawn 方式，worker 入口必须是
模块级函数（``_worker_main``），且调用方需在 ``if __name__ ==
"__main__"`` 保护下创建（GUI 入口已有）。
"""
import multiprocessing as _mp
import queue as _queue
import threading as _threading
import time as _time
from typing import Optional

from utils.log import get_logger

logger = get_logger("DecodeWorker")

# worker 心跳：超过这么久无响应视为已死（segfault 不会有任何输出）
_WORKER_TIMEOUT = 15.0

# 优化5：正则预编译（子进程内复用）
import re as _re
_TICKET_PAT = _re.compile(r"[A-Za-z0-9]{16,}")


def _worker_main(model_dir: str,
                 task_queue: "_mp.Queue",
                 result_queue: "_mp.Queue") -> None:
    """子进程入口：加载模型，循环解码。必须是模块级函数（spawn picklable）。"""
    try:
        import cv2
        import numpy as np
    except Exception as e:
        result_queue.put(("__init_error__", str(e)))
        return

    # 加载 WeChatQR 模型（与 ai_qr_scanner 同一套文件）
    import os
    detector = None
    try:
        prototxt = os.path.join(model_dir, "detect.prototxt")
        caffemodel = os.path.join(model_dir, "detect.caffemodel")
        sr_prototxt = os.path.join(model_dir, "sr.prototxt")
        sr_caffemodel = os.path.join(model_dir, "sr.caffemodel")
        if os.path.exists(prototxt) and os.path.exists(caffemodel):
            detector = cv2.wechat_qrcode_WeChatQR(
                prototxt, caffemodel, sr_prototxt, sr_caffemodel
            )
    except Exception as e:
        result_queue.put(("__init_error__", str(e)))
        return

    if detector is None:
        result_queue.put(("__init_error__", "WeChatQR not available"))
        return

    result_queue.put(("__ready__", ""))

    while True:
        try:
            task = task_queue.get()
        except Exception:
            break
        if task is None:  # 退出信号
            break
        try:
            # task: (task_id, bgr_numpy)
            task_id, img = task
            # WeChatQR 要 RGB（与主进程 try_decode_array 的 BGR 路径一致，
            # 这里直接转，避免主进程重复转换）
            if img.ndim == 3 and img.shape[2] == 3:
                rgb = cv2.cvtColor(img, cv2.COLOR_BGR2RGB)
            else:
                rgb = img
            decoded, _ = detector.detectAndDecode(rgb)
            ticket = None
            for code in decoded:
                if code:
                    try:
                        from utils.qr_payload import extract_kuro_ticket
                        ticket = extract_kuro_ticket(code)
                    except Exception:
                        ticket = _extract_ticket(code)
                    if ticket:
                        break
            result_queue.put((task_id, ticket))
        except Exception as e:
            try:
                result_queue.put((task[0] if task else "", None))
            except Exception:
                pass


def _extract_ticket(code: str) -> Optional[str]:
    """最小 ticket 提取（避免子进程 import 主进程重模块）。"""
    try:
        if "kuro" in code.lower() or "ticket" in code.lower():
            m = _TICKET_PAT.search(code)
            return m.group(0) if m else code
        return None
    except Exception:
        return None


class IsolatedDecoder:
    """主进程侧管理器：发送图片、收结果、worker 死亡自动重启。"""

    def __init__(self, model_dir: str = "ScanModel"):
        self._model_dir = model_dir
        self._proc: Optional[_mp.Process] = None
        self._task_q: Optional[_mp.Queue] = None
        self._result_q: Optional[_mp.Queue] = None
        self._task_seq = 0
        self._lock = _threading.Lock()
        self._restarts = 0

    # -- lifecycle ----------------------------------------------------

    def _alive(self) -> bool:
        return self._proc is not None and self._proc.is_alive()

    def _start(self) -> bool:
        """启动 worker，等待 ready（最多 30s，模型加载慢）。"""
        try:
            ctx = _mp.get_context("spawn")  # Windows/Linux 一致行为
            self._task_q = ctx.Queue()
            self._result_q = ctx.Queue()
            self._proc = ctx.Process(
                target=_worker_main,
                args=(self._model_dir, self._task_q, self._result_q),
                daemon=True,
                name="QRDecodeWorker",
            )
            self._proc.start()
            # 等 ready
            try:
                tag, payload = self._result_q.get(timeout=30.0)
                if tag == "__ready__":
                    logger.info("[DecodeWorker] worker ready (pid=%s)", self._proc.pid)
                    return True
                logger.warning("[DecodeWorker] worker init failed: %s", payload)
            except _queue.Empty:
                logger.warning("[DecodeWorker] worker start timeout")
            self._terminate()
            return False
        except Exception as e:
            logger.warning("[DecodeWorker] start failed: %s", e)
            return False

    def _terminate(self) -> None:
        try:
            if self._proc is not None:
                if self._proc.is_alive():
                    try:
                        self._task_q.put(None)
                    except Exception:
                        pass
                    self._proc.join(timeout=2.0)
                if self._proc.is_alive():
                    self._proc.terminate()
        except Exception:
            pass
        finally:
            self._proc = None

    def _ensure(self) -> bool:
        if self._alive():
            return True
        logger.info("[DecodeWorker] (re)starting worker...")
        ok = self._start()
        if ok:
            self._restarts += 1
        return ok

    def shutdown(self) -> None:
        """关闭子进程并清理队列，幂等。"""
        self._terminate()
        for q in (self._task_q, self._result_q):
            try:
                if q is not None:
                    q.close()
            except Exception:
                pass

    # -- decode -------------------------------------------------------

    def decode(self, bgr_array, timeout: float = _WORKER_TIMEOUT) -> Optional[str]:
        """解码一帧 BGR numpy，返回 ticket 或 None。

        worker segfault 时 get() 超时，自动重启并返回 None
        （调用方按 miss 处理，不闪退）。
        """
        with self._lock:
            if not self._ensure():
                return None
            self._task_seq += 1
            task_id = self._task_seq
            try:
                self._task_q.put((task_id, bgr_array))
            except Exception as e:
                logger.warning("[DecodeWorker] put failed: %s", e)
                return None
            try:
                # 只收属于本次 task 的结果（防止旧 worker 的延迟包串扰）
                deadline = _time.time() + timeout
                while True:
                    remain = deadline - _time.time()
                    if remain <= 0:
                        raise _queue.Empty
                    tag, payload = self._result_q.get(timeout=remain)
                    if tag == task_id:
                        return payload
                    # 非本次任务的结果（旧 worker 残留），丢弃
                    logger.debug("[DecodeWorker] discard stale result tag=%s", tag)
            except _queue.Empty:
                logger.warning(
                    "[DecodeWorker] decode timeout (worker may have crashed), restarting"
                )
                self._terminate()
                return None
            except Exception as e:
                logger.warning("[DecodeWorker] decode error: %s", e)
                return None

    @property
    def restarts(self) -> int:
        """返回子进程累计重启次数。"""
        return self._restarts
