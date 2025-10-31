# -*- coding: utf-8 -*-
"""登录对话框"""
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QMessageBox,
    QWidget
)
from PySide6.QtGui import QFont


class LoginDialog(QDialog):
    """登录对话框 - iOS风格"""
    
    login_success = Signal(dict)  # 登录成功信号
    
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("登录")
        self.setFixedSize(450, 420)
        self.setWindowFlags(Qt.Dialog | Qt.WindowCloseButtonHint)
        self.step = 1  # 当前步骤：1=输入手机号，2=输入验证码
        self.phone_number = ""  # 保存的手机号
        self.setup_ui()
        self.apply_styles()
    
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
        self.main_btn = QPushButton("下一步")
        self.main_btn.setFixedHeight(50)
        self.main_btn.clicked.connect(self.on_main_btn_click)
        layout.addWidget(self.main_btn)
        
        # 返回按钮（初始隐藏）
        self.back_btn = QPushButton("← 返回")
        self.back_btn.setFixedHeight(44)
        self.back_btn.clicked.connect(self.on_back)
        layout.addWidget(self.back_btn)
        self.back_btn.hide()
        
        # 添加弹性空间，确保元素向上聚集
        layout.addStretch(1)
    
    def apply_styles(self):
        """应用iOS风格样式"""
        self.setStyleSheet("""
            QDialog {
                background-color: #F5F5F7;
            }
            
            QLabel {
                color: #1D1D1F;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            
            QLineEdit {
                padding: 12px 16px;
                border: 1px solid #D2D2D7;
                border-radius: 12px;
                background-color: #FFFFFF;
                color: #1D1D1F;
                font-size: 14px;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            
            QLineEdit:focus {
                border: 2px solid #007AFF;
                padding: 11px 15px;
            }
            
            QPushButton {
                padding: 12px 24px;
                border: none;
                border-radius: 12px;
                background-color: #007AFF;
                color: #FFFFFF;
                font-size: 15px;
                font-weight: 600;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            
            QPushButton:hover {
                background-color: #0051D5;
            }
            
            QPushButton:pressed {
                background-color: #004FC4;
            }
            
            QPushButton:disabled {
                background-color: #D2D2D7;
                color: #8E8E93;
            }
            
            /* 返回按钮样式 */
            QPushButton#backBtn {
                background-color: #E5E5EA;
                color: #007AFF;
            }
            
            QPushButton#backBtn:hover {
                background-color: #D1D1D6;
            }
        """)
        self.back_btn.setObjectName("backBtn")
    
    def on_main_btn_click(self):
        """主按钮点击"""
        if self.step == 1:
            # 第一步：验证手机号并打开官网
            phone = self.phone_input.text().strip()
            
            if not phone or len(phone) != 11:
                QMessageBox.warning(
                    self, 
                    "提示", 
                    "请输入正确的11位手机号",
                    QMessageBox.Ok
                )
                return
            
            self.phone_number = phone
            
            # 打开官网
            import webbrowser
            webbrowser.open("https://www.kurobbs.com")
            
            # 显示详细提示
            msg_box = QMessageBox(self)
            msg_box.setWindowTitle("获取验证码")
            msg_box.setIcon(QMessageBox.Information)
            msg_box.setText(
                f"已在浏览器打开库街区官网\n\n"
                f"手机号：{phone}\n\n"
                f"⚠️ 重要提示 ⚠️\n\n"
                f"1. 在网页中输入手机号：{phone}\n"
                f"2. 点击【获取验证码】\n"
                f"3. 收到验证码后【直接复制】\n"
                f"4. 回到本程序，点击确定后粘贴验证码\n\n"
                f"⚠️ 请勿在网页上输入验证码！\n"
                f"   否则验证码将失效！"
            )
            msg_box.setStandardButtons(QMessageBox.Ok)
            msg_box.exec()
            
            # 切换到第二步
            self.step = 2
            self.title.setText("输入验证码")
            self.subtitle.setText(f"验证码已发送至 {phone[:3]}****{phone[-4:]}")
            self.phone_container.hide()
            self.code_container.show()
            self.main_btn.setText("登录")
            self.back_btn.show()
            self.code_input.setFocus()
            
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
    
    def on_back(self):
        """返回上一步"""
        self.step = 1
        self.title.setText("登录库街区")
        self.subtitle.setText("请输入手机号码")
        self.code_container.hide()
        self.phone_container.show()
        self.main_btn.setText("下一步")
        self.back_btn.hide()
        self.code_input.clear()
        self.phone_input.setFocus()

