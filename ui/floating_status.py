# -*- coding: utf-8 -*-
"""
桌面悬浮状态窗：小而置顶，显示抢码监控状态。

- 无边框、置顶、半透明
- 可拖动
- 显示：监控状态、平台/房间、今日检出次数、成功率
- 双击关闭
"""
from PySide6.QtWidgets import QWidget, QLabel, QVBoxLayout
from PySide6.QtCore import Qt, QTimer, QPoint
from PySide6.QtGui import QMouseEvent


class FloatingStatusWindow(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFixedSize(220, 110)

        # 背景样式
        self.setStyleSheet("""
            FloatingStatusWindow {
                background-color: rgba(30, 30, 30, 180);
                border-radius: 8px;
                border: 1px solid rgba(255, 255, 255, 30);
            }
            QLabel {
                color: white;
                font-size: 12px;
                background: transparent;
            }
            #title {
                font-size: 13px;
                font-weight: bold;
                color: #4CAF50;
            }
        """)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 8, 10, 8)
        layout.setSpacing(2)

        self.title_label = QLabel("🎯 抢码监控")
        self.title_label.setObjectName("title")
        layout.addWidget(self.title_label)

        self.status_label = QLabel("状态: 未启动")
        layout.addWidget(self.status_label)

        self.room_label = QLabel("房间: -")
        layout.addWidget(self.room_label)

        self.stats_label = QLabel("今日: 检出 0 | 成功 0")
        layout.addWidget(self.stats_label)

        # 拖动支持
        self._drag_pos: QPoint | None = None

        # 定时刷新（1秒）
        self._timer = QTimer(self)
        self._timer.timeout.connect(self.refresh)
        self._timer.start(1000)

        # 数据源（由主窗口设置）
        self._get_status = None

    def set_status_provider(self, provider) -> None:
        """设置状态数据源：provider() 返回 dict(status, room, detected, success)。"""
        self._get_status = provider

    def refresh(self) -> None:
        if self._get_status is None:
            return
        try:
            data = self._get_status()
            self.status_label.setText(f"状态: {data.get('status', '-')}")
            self.room_label.setText(f"房间: {data.get('room', '-')}")
            d = data.get('detected', 0)
            s = data.get('success', 0)
            self.stats_label.setText(f"今日: 检出 {d} | 成功 {s}")
        except Exception:
            pass

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if event.button() == Qt.MouseButton.LeftButton:
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            event.accept()

    def mouseMoveEvent(self, event: QMouseEvent) -> None:
        if self._drag_pos is not None and event.buttons() & Qt.MouseButton.LeftButton:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
            event.accept()

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:
        self._drag_pos = None

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:
        """双击关闭。"""
        self.hide()
