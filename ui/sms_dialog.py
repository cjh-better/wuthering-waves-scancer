# -*- coding: utf-8 -*-
"""
短信验证对话框（参考 KuRo_Scanner WindowSms）
60 秒倒计时、重发按钮、"记住本次验证"复选框
"""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QMessageBox,
)
from PySide6.QtGui import QFont


class SmsDialog(QDialog):
    """短信验证对话框"""

    COUNTDOWN_SECONDS = 60

    def __init__(self, token: str, mobile: str, parent=None):
        super().__init__(parent)
        self.token = token
        self.mobile = mobile
        self._sms_code = ""
        self._auto_login = False
        self._remaining = 0

        self.setWindowTitle("短信验证")
        self.setFixedSize(420, 220)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)

        self._setup_ui()
        self._apply_styles()

        # 自动发送验证码
        self._send_sms()

    # ------------------------------------------------------------------
    # UI
    # ------------------------------------------------------------------

    def _setup_ui(self):
        layout = QVBoxLayout(self)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 20, 24, 20)

        # 提示
        hint = QLabel(f"验证码将发送至 {self.mobile[:3]}****{self.mobile[-4:]}" if len(self.mobile) >= 7 else "验证码已发送")
        hint.setAlignment(Qt.AlignCenter)
        hint.setFont(QFont("PingFang SC", 12))
        layout.addWidget(hint)

        # 验证码输入 + 发送按钮
        code_row = QHBoxLayout()
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("请输入验证码")
        self.code_input.setMaxLength(6)
        self.code_input.setFixedHeight(42)
        code_row.addWidget(self.code_input, 3)

        self.send_btn = QPushButton("发送验证码")
        self.send_btn.setFixedHeight(42)
        self.send_btn.clicked.connect(self._send_sms)
        code_row.addWidget(self.send_btn, 1)
        layout.addLayout(code_row)

        # "记住本次验证"
        self.remember_checkbox = QCheckBox("记住本次验证（下次无需验证码）")
        self.remember_checkbox.setChecked(True)
        layout.addWidget(self.remember_checkbox)

        # 确认/取消按钮
        btn_row = QHBoxLayout()
        self.ok_btn = QPushButton("确认")
        self.ok_btn.setFixedHeight(40)
        self.ok_btn.clicked.connect(self._on_confirm)
        btn_row.addWidget(self.ok_btn)

        cancel_btn = QPushButton("取消")
        cancel_btn.setFixedHeight(40)
        cancel_btn.setObjectName("cancelBtn")
        cancel_btn.clicked.connect(self.reject)
        btn_row.addWidget(cancel_btn)
        layout.addLayout(btn_row)

        # 倒计时定时器
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick)

    def _apply_styles(self):
        self.setStyleSheet("""
            QDialog { background-color: #F5F5F7; }
            QLabel { color: #1D1D1F; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }
            QLineEdit {
                padding: 10px 14px; border: 1px solid #D2D2D7; border-radius: 10px;
                background-color: #FFFFFF; font-size: 14px;
            }
            QLineEdit:focus { border: 2px solid #007AFF; padding: 9px 13px; }
            QPushButton {
                border: none; border-radius: 10px; background-color: #007AFF;
                color: #FFFFFF; font-size: 14px; font-weight: 600; padding: 8px 16px;
            }
            QPushButton:hover { background-color: #0051D5; }
            QPushButton:disabled { background-color: #D2D2D7; color: #8E8E93; }
            QPushButton#cancelBtn { background-color: #E5E5EA; color: #007AFF; }
            QPushButton#cancelBtn:hover { background-color: #D1D1D6; }
            QCheckBox { color: #1D1D1F; font-size: 13px; spacing: 6px; }
        """)

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _send_sms(self):
        """发送短信验证码并启动倒计时。

        正常路径直接发送；若服务端要求 GeeTest 验证（见
        ``KuroAPI.is_captcha_required``），弹出验证窗口，验证通过后
        携带 geeTestData 重发（照搬 KuRo_Scanner C++ 逻辑）。
        """
        from utils.kuro_api import kuro_api
        result = kuro_api.send_sms()
        if kuro_api.is_captcha_required(result):
            gee_data = self._run_geetest()
            if gee_data is None:
                return  # 用户取消 / 组件不可用：不启动倒计时
            result = kuro_api.send_sms(gee_data)
        if result.get("code") == 200:
            self._start_countdown()
        else:
            msg = result.get("msg", "发送失败")
            QMessageBox.warning(self, "发送失败", msg)
            # 即使失败也启动倒计时（防止频繁请求）
            self._start_countdown()

    def _run_geetest(self):
        """弹出 GeeTest 验证窗口，返回验证 JSON 字符串（失败/取消返回 None）。"""
        try:
            from ui.geetest_dialog import GeeTestDialog, WEBENGINE_AVAILABLE
        except Exception as e:
            QMessageBox.warning(self, "验证", f"验证码组件加载失败：{e}")
            return None
        if not WEBENGINE_AVAILABLE:
            QMessageBox.warning(
                self, "验证",
                "当前环境缺少浏览器组件（QtWebEngine），无法显示验证码。\n"
                "请换一台能正常显示的 Windows 电脑重试。",
            )
            return None
        dlg = GeeTestDialog(self)
        if dlg.exec() != QDialog.Accepted:
            return None
        res = dlg.get_validate_result()
        if not res:
            return None
        import json
        return json.dumps(res, ensure_ascii=False)

    def _start_countdown(self):
        self._remaining = self.COUNTDOWN_SECONDS
        self.send_btn.setEnabled(False)
        self.send_btn.setText(f"重新发送({self._remaining}s)")
        self._timer.start()

    def _tick(self):
        self._remaining -= 1
        if self._remaining <= 0:
            self._timer.stop()
            self.send_btn.setEnabled(True)
            self.send_btn.setText("重新发送")
        else:
            self.send_btn.setText(f"重新发送({self._remaining}s)")

    def _on_confirm(self):
        code = self.code_input.text().strip()
        if not code:
            QMessageBox.warning(self, "提示", "请输入验证码")
            return
        self._sms_code = code
        self._auto_login = self.remember_checkbox.isChecked()
        self.accept()

    # ------------------------------------------------------------------
    # Public getters (call after exec())
    # ------------------------------------------------------------------

    def get_sms_code(self) -> str:
        return self._sms_code

    def get_auto_login(self) -> bool:
        return self._auto_login
