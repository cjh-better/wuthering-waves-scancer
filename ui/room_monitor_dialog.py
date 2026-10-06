# -*- coding: utf-8 -*-
"""开播监控对话框：管理监控房间列表，查看开播状态。"""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QSpinBox, QMessageBox,
)

from utils.config_manager import config_manager
from utils.log import get_logger
from utils.room_monitor import RoomMonitorThread


logger = get_logger("RoomMonitor")


class RoomMonitorDialog(QDialog):
    """多房间开播监控。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("开播监控")
        self.setMinimumSize(520, 400)

        self.monitor = RoomMonitorThread(self)
        self.monitor.room_status.connect(self._on_room_status)
        self.monitor.room_live.connect(self._on_room_live)

        self._setup_ui()
        self._load_rooms()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        # 房间表格
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(["平台", "房间号", "备注", "状态"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectRows)
        layout.addWidget(self.table)

        # 添加房间行
        add_row = QHBoxLayout()
        self.platform_combo = QComboBox()
        self.platform_combo.addItems(["douyin", "bilibili"])
        add_row.addWidget(self.platform_combo)
        self.room_input = QLineEdit()
        self.room_input.setPlaceholderText("房间号或分享链接")
        add_row.addWidget(self.room_input, 2)
        self.name_input = QLineEdit()
        self.name_input.setPlaceholderText("备注（可选）")
        add_row.addWidget(self.name_input, 1)
        add_btn = QPushButton("添加")
        add_btn.clicked.connect(self._on_add_room)
        add_row.addWidget(add_btn)
        del_btn = QPushButton("删除")
        del_btn.clicked.connect(self._on_del_room)
        add_row.addWidget(del_btn)
        layout.addLayout(add_row)

        # 控制行
        ctrl_row = QHBoxLayout()
        ctrl_row.addWidget(QLabel("轮询间隔（秒）:"))
        self.interval_spin = QSpinBox()
        self.interval_spin.setRange(10, 600)
        self.interval_spin.setValue(int(config_manager.get("monitor_interval", 60)))
        ctrl_row.addWidget(self.interval_spin)
        self.toggle_btn = QPushButton("开始监控")
        self.toggle_btn.clicked.connect(self._on_toggle)
        ctrl_row.addWidget(self.toggle_btn)
        ctrl_row.addStretch()
        layout.addLayout(ctrl_row)

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _load_rooms(self):
        rooms = config_manager.get("monitor_rooms", [])
        self.table.setRowCount(0)
        for r in rooms:
            self._add_table_row(
                r.get("platform", "douyin"),
                r.get("room_id", ""),
                r.get("name", ""),
                "未检查",
            )

    def _save_rooms(self):
        rooms = []
        for row in range(self.table.rowCount()):
            rooms.append({
                "platform": self.table.item(row, 0).text(),
                "room_id": self.table.item(row, 1).text(),
                "name": self.table.item(row, 2).text(),
            })
        config_manager.set("monitor_rooms", rooms)

    def _add_table_row(self, platform, room_id, name, status):
        row = self.table.rowCount()
        self.table.insertRow(row)
        for col, text in enumerate([platform, room_id, name, status]):
            item = QTableWidgetItem(text)
            if col == 3:
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            self.table.setItem(row, col, item)

    def _on_add_room(self):
        from utils import room_url
        platform = self.platform_combo.currentText()
        text = self.room_input.text().strip()
        name = self.name_input.text().strip()
        if not text:
            return
        # 支持分享链接/短链
        room_id = room_url.extract_room_id(text, platform)
        if not room_id:
            short = room_url.find_short_link(text)
            if short:
                room_id = room_url.resolve_room_id(short, platform)
        if not room_id:
            QMessageBox.warning(self, "提示", "无法识别房间号")
            return
        self._add_table_row(platform, room_id, name, "未检查")
        self._save_rooms()
        self.room_input.clear()
        self.name_input.clear()
        self._push_rooms_to_monitor()

    def _on_del_room(self):
        row = self.table.currentRow()
        if row < 0:
            return
        self.table.removeRow(row)
        self._save_rooms()
        self._push_rooms_to_monitor()

    def _push_rooms_to_monitor(self):
        rooms = []
        for row in range(self.table.rowCount()):
            rooms.append((
                self.table.item(row, 0).text(),
                self.table.item(row, 1).text(),
                self.table.item(row, 2).text(),
            ))
        self.monitor.set_rooms(rooms)

    def _on_toggle(self):
        if self.monitor.isRunning() and self.monitor._running:
            self.monitor.stop_monitoring()
            self.toggle_btn.setText("开始监控")
        else:
            interval = self.interval_spin.value()
            config_manager.set("monitor_interval", interval)
            self.monitor.set_interval(interval)
            self._push_rooms_to_monitor()
            # 状态列重置为检查中
            for row in range(self.table.rowCount()):
                self.table.item(row, 3).setText("检查中")
            self.monitor.start_monitoring()
            self.toggle_btn.setText("停止监控")

    def _on_room_status(self, platform, room_id, status, title):
        for row in range(self.table.rowCount()):
            if (self.table.item(row, 0).text() == platform
                    and self.table.item(row, 1).text() == room_id):
                item = self.table.item(row, 3)
                item.setText(status)
                # 开播高亮
                if status == "Normal":
                    item.setBackground(Qt.green)
                else:
                    item.setBackground(Qt.transparent)
                break

    def _on_room_live(self, platform, room_id, display):
        QMessageBox.information(
            self, "开播提醒",
            f"🔴 {display} 开播了！\n平台: {platform} 房间: {room_id}",
        )

    def closeEvent(self, event):
        self.monitor.stop_monitoring()
        if self.monitor.isRunning():
            self.monitor.wait(3000)
        super().closeEvent(event)
