# -*- coding: utf-8 -*-
"""
短信验证对话框（参考 KuRo_Scanner WindowSms）
60 秒倒计时、重发按钮、"记住本次验证"复选框
"""
from typing import Optional

from PySide6.QtCore import Qt, QTimer, QThread, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QMessageBox,
)
from PySide6.QtGui import QFont


class SmsSendWorker(QThread):
    """后台发送短信验证码（send_sms 是同步网络请求，最长 5s）。

    GeeTest 验证必须在 UI 线程弹模态框，因此 worker 只负责纯网络
    发送；若服务端要求验证，UI 线程弹完 GeeTest 后再起一个 worker
    带着 geeTestData 重发。
    """

    done = Signal(dict)  # send_sms 的原始返回

    def __init__(self, gee_test_data: str = "", parent=None):
        super().__init__(parent)
        self.gee_test_data = gee_test_data

    def run(self):
        try:
            from utils.kuro_api import kuro_api
            result = kuro_api.send_sms(self.gee_test_data)
            if not isinstance(result, dict):
                result = {"code": -1, "msg": "发送失败"}
        except Exception as e:
            result = {"code": -1, "msg": f"发送失败: {e}"}
        self.done.emit(result)


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
        self._sms_worker: Optional[SmsSendWorker] = None

        self.setWindowTitle("短信验证")
        self.setFixedSize(420, 220)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)

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
        from ui.theme import get_stylesheet, THEME_DARK
        from utils.config_manager import config_manager
        theme = config_manager.get("theme", THEME_DARK)
        self.setStyleSheet(get_stylesheet(theme))

    # ------------------------------------------------------------------
    # Logic
    # ------------------------------------------------------------------

    def _send_sms(self):
        """发送短信验证码并启动倒计时（网络部分在后台线程）。

        正常路径直接发送；若服务端要求 GeeTest 验证（见
        ``KuroAPI.is_captcha_required``），在 UI 线程弹出验证窗口，
        验证通过后带着 geeTestData 起后台线程重发（照搬 KuRo_Scanner
        C++ 逻辑）。
        """
        self._start_send_worker()

    def _start_send_worker(self, gee_test_data: str = ""):
        """起一个后台线程发送验证码（防重复点击）。"""
        if self._sms_worker and self._sms_worker.isRunning():
            return
        self.send_btn.setEnabled(False)
        self.send_btn.setText("发送中...")
        self._sms_worker = SmsSendWorker(gee_test_data, parent=self)
        self._sms_worker.done.connect(self._on_sms_sent)
        self._sms_worker.finished.connect(self._on_sms_worker_finished)
        self._sms_worker.start()

    def _on_sms_worker_finished(self):
        self._sms_worker = None

    def _on_sms_sent(self, result: dict):
        """后台发送完成（UI 线程）：处理验证要求 / 成功 / 失败。"""
        from utils.kuro_api import kuro_api
        if kuro_api.is_captcha_required(result):
            self.send_btn.setEnabled(True)
            self.send_btn.setText("发送验证码")
            gee_data = self._run_geetest()
            if gee_data is None:
                return  # 用户取消 / 组件不可用：不启动倒计时
            self._start_send_worker(gee_data)
            return
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

    def closeEvent(self, event):
        if self._sms_worker and self._sms_worker.isRunning():
            try:
                self._sms_worker.wait(6000)
            except Exception:
                pass
        super().closeEvent(event)

    # ------------------------------------------------------------------
    # Public getters (call after exec())
    # ------------------------------------------------------------------

    def get_sms_code(self) -> str:
        return self._sms_code

    def get_auto_login(self) -> bool:
        return self._auto_login
