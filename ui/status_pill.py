# -*- coding: utf-8 -*-
"""
状态胶囊：带呼吸灯动效的状态指示器。

- 待机：灰色圆点
- 监控中：青色圆点 + 呼吸脉冲动画
- 登录中：金色圆点 + 呼吸脉冲
"""
from PySide6.QtWidgets import QWidget, QLabel, QHBoxLayout
from PySide6.QtCore import QPropertyAnimation, QEasingCurve, Property


class StatusPill(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("statusPill")

        layout = QHBoxLayout(self)
        layout.setContentsMargins(16, 8, 16, 8)
        layout.setSpacing(10)

        # 呼吸灯圆点
        self._dot = QLabel()
        self._dot.setFixedSize(10, 10)
        self._dot.setStyleSheet(
            "background-color: #5C6678; border-radius: 5px;"
        )
        layout.addWidget(self._dot)

        self._label = QLabel("待机中")
        self._label.setStyleSheet(
            "color: #9AA4B8; font-size: 12.5px; background: transparent;"
        )
        layout.addWidget(self._label)
        layout.addStretch()

        # 呼吸动画（透明度脉冲）
        self._opacity = 1.0
        self._anim = QPropertyAnimation(self, b"dotOpacity")
        self._anim.setDuration(1200)
        self._anim.setStartValue(1.0)
        self._anim.setEndValue(0.35)
        self._anim.setEasingCurve(QEasingCurve.Type.InOutSine)
        self._anim.setLoopCount(-1)  # 无限循环

        self.setStyleSheet("""
            QWidget#statusPill {
                background-color: rgba(255, 255, 255, 0.03);
                border: 1px solid #232B3D;
                border-radius: 20px;
            }
        """)

    def _get_dot_opacity(self) -> float:
        return self._opacity

    def _set_dot_opacity(self, value: float) -> None:
        self._opacity = value
        # 通过样式表更新透明度（用 rgba）
        color = self._dot_color
        self._dot.setStyleSheet(
            f"background-color: rgba({color[0]}, {color[1]}, {color[2]}, {value:.2f});"
            "border-radius: 5px;"
        )

    dotOpacity = Property(float, _get_dot_opacity, _set_dot_opacity)

    def set_status(self, text: str, mode: str = "idle") -> None:
        """设置状态。

        Args:
            text: 状态文字
            mode: idle（灰）/ active（青，呼吸）/ working（金，呼吸）
        """
        # U4优化：相同状态不重复应用样式，避免触发不必要的 repaint
        if getattr(self, "_last_status", None) == (text, mode):
            return
        self._last_status = (text, mode)
        self._label.setText(text)
        if mode == "active":
            self._dot_color = (62, 214, 164)  # 青
            self._label.setStyleSheet(
                "color: #3ED6A4; font-size: 12.5px; background: transparent; font-weight: 600;"
            )
            self._anim.start()
        elif mode == "working":
            self._dot_color = (201, 168, 106)  # 金
            self._label.setStyleSheet(
                "color: #C9A86A; font-size: 12.5px; background: transparent; font-weight: 600;"
            )
            self._anim.start()
        else:
            self._anim.stop()
            self._dot_color = (92, 102, 120)  # 灰
            self._dot.setStyleSheet(
                "background-color: #5C6678; border-radius: 5px;"
            )
            self._label.setStyleSheet(
                "color: #9AA4B8; font-size: 12.5px; background: transparent;"
            )

    _dot_color = (92, 102, 120)
