# -*- coding: utf-8 -*-
"""登录对话框"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox,
    QWidget
)
from PySide6.QtGui import QFont


class LoginDialog(QDialog):
    """登录对话框 - iOS风格"""
    
    login_success = Signal(dict)  # 登录成功信号
    
    COUNTDOWN_SECONDS = 60

    def __init__(self, parent=None, mobile: str = ""):
        super().__init__(parent)
        self.setWindowTitle("登录")
        self.setFixedSize(450, 460)
        self.setWindowFlags(Qt.WindowType.Dialog | Qt.WindowType.WindowCloseButtonHint)
        self.step = 1  # 当前步骤：1=输入手机号，2=输入验证码
        self.phone_number = ""  # 保存的手机号
        self._remaining = 0  # 重发倒计时
        self.setup_ui()
        self.apply_styles()

        # 倒计时定时器（验证码重发）
        from PySide6.QtCore import QTimer
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._tick_countdown)

        if mobile:
            # 一键续期场景：预填手机号并自动发送验证码
            self.phone_input.setText(mobile)
            QTimer.singleShot(300, self._auto_send_for_renew)
    
    def setup_ui(self):
        """设置 UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(20)
        layout.setContentsMargins(40, 35, 40, 35)
        
        # 标题
        self.title = QLabel("登录库街区")
        self.title.setAlignment(Qt.AlignCenter)
        title_font = QFont("PingFang SC", 18)
        title_font.setBold(True)
        self.title.setFont(title_font)
        layout.addWidget(self.title)
        
        # 副标题/提示文本
        self.subtitle = QLabel("请输入手机号码")
        self.subtitle.setAlignment(Qt.AlignCenter)
        subtitle_font = QFont("PingFang SC", 12)
        self.subtitle.setFont(subtitle_font)
        layout.addWidget(self.subtitle)
        
        layout.addSpacing(15)
        
        # 手机号输入区域
        self.phone_container = QWidget()
        phone_layout = QVBoxLayout(self.phone_container)
        phone_layout.setContentsMargins(0, 0, 0, 0)
        phone_layout.setSpacing(8)
        
        phone_label = QLabel("手机号")
        phone_label_font = QFont("PingFang SC", 11)
        phone_label.setFont(phone_label_font)
        phone_layout.addWidget(phone_label)
        
        self.phone_input = QLineEdit()
        self.phone_input.setPlaceholderText("输入11位手机号")
        self.phone_input.setMaxLength(11)
        self.phone_input.setFixedHeight(45)
        phone_layout.addWidget(self.phone_input)
        
        layout.addWidget(self.phone_container)
        
        # 验证码输入区域（初始隐藏）
        self.code_container = QWidget()
        code_layout = QVBoxLayout(self.code_container)
        code_layout.setContentsMargins(0, 0, 0, 0)
        code_layout.setSpacing(8)
        
        code_label = QLabel("验证码")
        code_label_font = QFont("PingFang SC", 11)
        code_label.setFont(code_label_font)
        code_layout.addWidget(code_label)
        
        self.code_input = QLineEdit()
        self.code_input.setPlaceholderText("输入6位验证码")
        self.code_input.setMaxLength(6)
        self.code_input.setFixedHeight(45)
        code_layout.addWidget(self.code_input)
        
        layout.addWidget(self.code_container)
        self.code_container.hide()  # 初始隐藏
        
        layout.addSpacing(15)
        
        # 主按钮
        self.main_btn = QPushButton("获取验证码")
        self.main_btn.setFixedHeight(50)
        self.main_btn.clicked.connect(self.on_main_btn_click)
        layout.addWidget(self.main_btn)
        
        # 重新发送按钮（第二步显示，带倒计时）
        self.resend_btn = QPushButton("重新发送")
        self.resend_btn.setFixedHeight(40)
        self.resend_btn.setObjectName("backBtn")
        self.resend_btn.clicked.connect(self._on_resend)
        layout.addWidget(self.resend_btn)
        self.resend_btn.hide()

        # 返回按钮（初始隐藏）
        self.back_btn = QPushButton("← 返回")
        self.back_btn.setFixedHeight(44)
        self.back_btn.clicked.connect(self.on_back)
        layout.addWidget(self.back_btn)
        self.back_btn.hide()
        
        # 添加弹性空间，确保元素向上聚集
        layout.addStretch(1)

        # 回车直接提交 + 打开即聚焦手机号
        self.phone_input.returnPressed.connect(self.on_main_btn_click)
        self.code_input.returnPressed.connect(self.on_main_btn_click)
        self.phone_input.setFocus()
    
    def apply_styles(self):
        """应用当前主题样式（跟随主窗口深色/浅色）。"""
        from ui.theme import get_stylesheet, THEME_DARK
        from utils.config_manager import config_manager
        theme = config_manager.get("theme", THEME_DARK)
        # 对话框用主样式表 + 对话框背景覆盖
        self.setStyleSheet(get_stylesheet(theme))
        self.back_btn.setObjectName("backBtn")
    
    def on_main_btn_click(self):
        """主按钮点击"""
        if self.step == 1:
            # 第一步：验证手机号，直接调 API 发送验证码（借鉴 kuro.py 思路）
            import re
            phone = self.phone_input.text().strip()

            if not re.fullmatch(r"1[3-9]\d{9}", phone or ""):
                QMessageBox.warning(
                    self,
                    "提示",
                    "请输入正确的11位手机号",
                    QMessageBox.Ok
                )
                self.phone_input.setFocus()
                self.phone_input.selectAll()
                return

            self.phone_number = phone

            # 禁用按钮防重复点击
            self.main_btn.setEnabled(False)
            self.main_btn.setText("发送中...")

            try:
                from utils.kuro_api import kuro_api
                result = kuro_api.send_sms_code(phone)
            finally:
                self.main_btn.setEnabled(True)
                self.main_btn.setText("获取验证码")

            if result.get("code") == 200 and not result.get("need_geetest"):
                # API 发送成功，直接进第二步
                self._goto_step2(phone)
                return

            if result.get("need_geetest"):
                # 触发极验：弹滑块验证，通过后重试
                if self._solve_geetest_and_retry(phone):
                    return
                # 滑块失败/取消 → 降级走浏览器
            else:
                self._log_sms_fallback(result.get("msg", "发送失败"))

            # 降级：打开官网手动获取（原流程保留）
            self._fallback_to_browser(phone)
        else:
            # 第二步：执行登录
            code = self.code_input.text().strip()
            
            if not code or len(code) < 4:
                QMessageBox.warning(self, "提示", "请输入验证码")
                return
            
            # 禁用按钮
            self.main_btn.setEnabled(False)
            self.main_btn.setText("登录中...")
            self.back_btn.setEnabled(False)
            
            # 执行登录
            from utils.kuro_api import kuro_api
            result = kuro_api.login(self.phone_number, code)
            
            if result.get("code") == 200:
                data = result.get("data", {})
                self.login_success.emit(data)
                QMessageBox.information(self, "成功", "登录成功！")
                self.accept()
            else:
                msg = result.get("msg", "登录失败")
                QMessageBox.warning(self, "登录失败", f"{msg}\n\n请检查验证码是否正确")
                self.main_btn.setEnabled(True)
                self.main_btn.setText("登录")
                self.back_btn.setEnabled(True)

    def _goto_step2(self, phone: str):
        """切换到第二步：输入验证码"""
        self.step = 2
        self.title.setText("输入验证码")
        self.subtitle.setText(f"验证码已发送至 {phone[:3]}****{phone[-4:]}")
        self.phone_container.hide()
        self.code_container.show()
        self.main_btn.setText("登录")
        self.resend_btn.show()
        self.back_btn.show()
        self.code_input.setFocus()
        self._start_countdown()

    # ------------------------------------------------------------------
    # 验证码重发倒计时
    # ------------------------------------------------------------------
    def _auto_send_for_renew(self):
        """一键续期场景：打开后自动发送验证码，省一次点击。"""
        if self.step == 1 and self.phone_input.text().strip():
            self.on_main_btn_click()

    def _on_resend(self):
        """重新发送验证码（倒计时结束后可点）。"""
        if self._remaining > 0 or self.step != 2:
            return
        phone = self.phone_number
        if not phone:
            return
        self.resend_btn.setEnabled(False)
        self.resend_btn.setText("发送中...")
        try:
            from utils.kuro_api import kuro_api
            result = kuro_api.send_sms_code(phone)
        finally:
            pass
        if result.get("code") == 200 and not result.get("need_geetest"):
            self._start_countdown()
        elif result.get("need_geetest"):
            if self._solve_geetest_and_retry(phone):
                return
            self.resend_btn.setEnabled(True)
            self.resend_btn.setText("重新发送")
        else:
            msg = result.get("msg", "发送失败")
            # 发送频繁等可恢复错误：给明确指引而非干巴巴报错
            hint = self._friendly_sms_error(msg)
            QMessageBox.warning(self, "发送失败", hint)
            self.resend_btn.setEnabled(True)
            self.resend_btn.setText("重新发送")

    def _start_countdown(self):
        """启动 60 秒重发倒计时。"""
        self._remaining = self.COUNTDOWN_SECONDS
        self.resend_btn.setEnabled(False)
        self._tick_countdown()
        self._timer.start()

    def _tick_countdown(self):
        if self._remaining <= 0:
            self._timer.stop()
            self.resend_btn.setEnabled(True)
            self.resend_btn.setText("重新发送")
        else:
            self.resend_btn.setText(f"重新发送({self._remaining}s)")
            self._remaining -= 1

    def _friendly_sms_error(self, msg: str) -> str:
        """把服务端错误翻译成用户能懂的指引。"""
        m = (msg or "").lower()
        if "频繁" in m or "frequency" in m or "too many" in m:
            return f"发送太频繁，请{self.COUNTDOWN_SECONDS}秒后再试。\n\n(服务端：{msg})"
        if "无效" in m or "invalid" in m:
            return f"手机号无效，请检查后重试。\n\n(服务端：{msg})"
        if "上限" in m or "limit" in m:
            return f"今日发送次数已达上限，请明天再试或走浏览器手动获取。\n\n(服务端：{msg})"
        return msg

    def _solve_geetest_and_retry(self, phone: str) -> bool:
        """极验滑块验证，通过后重试发送短信。成功返回 True。"""
        try:
            from ui.geetest_dialog import GeeTestDialog
        except Exception:
            return False
        dlg = GeeTestDialog(self)
        if dlg.exec() != dlg.Accepted:
            return False
        validate = dlg.get_validate_result() or {}
        import json
        geetest_data = json.dumps(validate) if validate else ""
        if not geetest_data:
            return False
        from utils.kuro_api import kuro_api
        result = kuro_api.send_sms_code(phone, geetest_data=geetest_data)
        if result.get("code") == 200 and not result.get("need_geetest"):
            self._goto_step2(phone)
            return True
        return False

    def _log_sms_fallback(self, reason: str):
        """记录 API 发送失败原因（调试用）。"""
        try:
            from utils.logger import get_logger
            get_logger("LoginDialog").warning(f"[Login] API发短信失败({reason})，降级走浏览器")
        except Exception:
            pass

    def _fallback_to_browser(self, phone: str):
        """降级方案：打开官网手动获取验证码（原流程）。"""
        import webbrowser
        webbrowser.open("https://www.kurobbs.com")

        msg_box = QMessageBox(self)
        msg_box.setWindowTitle("获取验证码")
        msg_box.setIcon(QMessageBox.Information)
        msg_box.setText(
            f"已在浏览器打开库街区官网\n\n"
            f"手机号：{phone}\n\n"
            f"1. 在网页中输入手机号：{phone}\n"
            f"2. 点击【获取验证码】\n"
            f"3. 收到验证码后【直接复制】\n"
            f"4. 回到本程序，点击确定后粘贴验证码\n\n"
            f"⚠️ 请勿在网页上输入验证码！\n"
            f"   否则验证码将失效！"
        )
        msg_box.setStandardButtons(QMessageBox.Ok)
        msg_box.exec()

        self._goto_step2(phone)

    
    def on_back(self):
        """返回上一步"""
        self.step = 1
        self.title.setText("登录库街区")
        self.subtitle.setText("请输入手机号码")
        self.code_container.hide()
        self.phone_container.show()
        self.main_btn.setText("获取验证码")
        self.back_btn.hide()
        self.code_input.clear()
        self.phone_input.setFocus()

