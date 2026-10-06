# -*- coding: utf-8 -*-
"""多房间开播监控：轻量轮询直播状态，开播时通知。

设计原则：
- 只查状态，不拉视频流：复用平台适配器的 fetch()（API 调用，不建流连接）。
- 轮询在工作线程，UI 只收 signal。
- 状态变化（未开播 -> 开播）才通知，避免刷屏。
"""
import threading
import time
from typing import Dict, List, Tuple

from PySide6.QtCore import QThread, Signal

from utils.log import get_logger
from utils.platforms.base import LiveStreamStatus


logger = get_logger("RoomMonitor")


class RoomMonitorThread(QThread):
    """后台轮询房间开播状态。"""

    # (platform, room_id, status_name, title)
    room_status = Signal(str, str, str, str)
    # (platform, room_id) 开播通知（仅未开播->开播的跃迁触发）
    room_live = Signal(str, str, str)  # (platform, room_id, title)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._rooms: List[Tuple[str, str, str]] = []  # (platform, room_id, name)
        self._rooms_lock = threading.Lock()
        self._interval = 60.0
        self._running = False
        self._last_status: Dict[Tuple[str, str], str] = {}

    def set_rooms(self, rooms: List[Tuple[str, str, str]]):
        with self._rooms_lock:
            self._rooms = list(rooms)

    def set_interval(self, seconds: float):
        self._interval = max(10.0, seconds)

    def start_monitoring(self):
        self._running = True
        if not self.isRunning():
            self.start()

    def stop_monitoring(self):
        self._running = False

    def _get_rooms(self) -> List[Tuple[str, str, str]]:
        with self._rooms_lock:
            return list(self._rooms)

    def _check_one(self, session, platform: str, room_id: str) -> Tuple[str, str]:
        """查单个房间状态，返回 (status_name, title)。永不抛异常。

        session 由调用方传入并复用：Douyin 的 ttwid cookie 需要跨请求
        保持，否则每次都像新设备，容易触发风控；TCP/TLS 复用也更快。
        """
        try:
            from utils.platforms.bilibili import BilibiliAdapter
            from utils.platforms.douyin import DouyinAdapter

            adapter = BilibiliAdapter(session) if platform == "bilibili" else DouyinAdapter(session)
            info = adapter.fetch(room_id)
            status_name = info.status.name
            # 标题：优先用 detail，没有则用状态名
            title = info.detail or status_name
            return status_name, title
        except Exception as e:
            logger.warning("[RoomMonitor] 查询 %s/%s 失败: %s", platform, room_id, e)
            return "Error", str(e)

    def run(self):
        logger.info("[RoomMonitor] 监控线程启动")
        from utils import http as http_utils
        # 线程生命周期内复用一个 session（cookie 保持、连接复用）
        session = http_utils.new_session()
        while self._running:
            rooms = self._get_rooms()
            for platform, room_id, name in rooms:
                if not self._running:
                    break
                status_name, title = self._check_one(session, platform, room_id)
                key = (platform, room_id)
                prev = self._last_status.get(key)
                self._last_status[key] = status_name
                self.room_status.emit(platform, room_id, status_name, title)
                # 跃迁通知：之前不是开播，现在开播了
                if status_name == LiveStreamStatus.Normal.name and prev != LiveStreamStatus.Normal.name:
                    display = name or room_id
                    self.room_live.emit(platform, room_id, display)
                    logger.info("[RoomMonitor] 🔴 %s 开播了！", display)
            # 可中断的等待（sleep 不超过剩余时间，避免 overshoot）
            deadline = time.monotonic() + self._interval
            while self._running:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                time.sleep(min(0.5, remaining))
        logger.info("[RoomMonitor] 监控线程退出")
