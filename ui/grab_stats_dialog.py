# -*- coding: utf-8 -*-
"""抢码战绩对话框：成功率、平均耗时、最快/最慢。"""
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
)

from utils.grab_stats import grab_stats


class GrabStatsDialog(QDialog):
    """抢码战绩看板。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("抢码战绩")
        self.setMinimumSize(360, 260)
        self._setup_ui()
        self._refresh()

    def _setup_ui(self):
        layout = QVBoxLayout(self)

        self.stats_label = QLabel()
        self.stats_label.setStyleSheet("font-size: 14px;")
        layout.addWidget(self.stats_label)

        hint = QLabel("统计口径：从检出二维码到登录完成的端到端耗时。")
        hint.setStyleSheet("color: gray; font-size: 11px;")
        hint.setWordWrap(True)
        layout.addWidget(hint)

        btn_row = QHBoxLayout()
        refresh_btn = QPushButton("刷新")
        refresh_btn.clicked.connect(self._refresh)
        btn_row.addWidget(refresh_btn)
        clear_btn = QPushButton("清零")
        clear_btn.clicked.connect(self._on_clear)
        btn_row.addWidget(clear_btn)
        btn_row.addStretch()
        layout.addLayout(btn_row)

    def _refresh(self):
        s = grab_stats.summary()
        self.stats_label.setText(
            f"抢码次数：{s['total']}\n"
            f"成功：{s['success']}　失败：{s['failed']}\n"
            f"成功率：{s['success_rate']:.1f}%\n"
            f"平均耗时：{s['avg_ms']:.0f} ms\n"
            f"最快：{s['fastest_ms']:.0f} ms　最慢：{s['slowest_ms']:.0f} ms"
        )

    def _on_clear(self):
        grab_stats.reset()
        self._refresh()
