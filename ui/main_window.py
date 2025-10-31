# -*- coding: utf-8 -*-
"""主窗口"""
import os
import sys
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QInputDialog, QLineEdit
)
from PySide6.QtGui import QFont, QIcon
from ui.login_dialog import LoginDialog
from ui.scan_window import ScanWindow
from utils.config_manager import config_manager
from utils.kuro_api import kuro_api

# 🚀 导入性能监控
try:
    from utils.performance_monitor import perf_monitor
    PERF_MONITOR_AVAILABLE = True
except Exception:
    PERF_MONITOR_AVAILABLE = False


class ScanThread(QThread):
    """扫码线程"""
    
    scan_result = Signal(dict)  # 扫码结果信号
    log_message = Signal(str)  # 日志消息信号
    
    def __init__(self, qr_code, parent=None, skip_role_check=False):
        super().__init__(parent)
        self.qr_code = qr_code
        self.verify_code = ""
        self.skip_role_check = skip_role_check  # 是否跳过角色验证（重试时跳过）
    
    def run(self):
        """⚡ 执行扫码 - 终极优化版（集成性能监控）"""
        try:
            # 验证QR码有效性（必须步骤，否则会401）
            if not self.skip_role_check:
                role_result = kuro_api.get_role_infos(self.qr_code)
                
                # 🚀 性能监控：记录roleInfos完成
                if PERF_MONITOR_AVAILABLE and perf_monitor.current_scan:
                    perf_monitor.mark_api_roleinfo_done()
            
                if role_result.get("code") == 220:
                    self.log_message.emit("❌ Token已过期")
                    self.scan_result.emit({"success": False, "message": "Token已过期"})
                    if PERF_MONITOR_AVAILABLE:
                        perf_monitor.end_scan(success=False)
                    return
                elif role_result.get("code") == 2209:
                    self.log_message.emit("❌ 二维码已过期")
                    self.scan_result.emit({"success": False, "message": "二维码已过期"})
                    if PERF_MONITOR_AVAILABLE:
                        perf_monitor.end_scan(success=False)
                    return
                elif role_result.get("code") != 200:
                    msg = role_result.get("msg", "验证失败")
                    self.log_message.emit(f"❌ {msg}")
                    self.scan_result.emit({"success": False, "message": msg})
                    if PERF_MONITOR_AVAILABLE:
                        perf_monitor.end_scan(success=False)
                    return
            
            # 提交扫码（无中间日志，减少UI更新开销）
            scan_result = kuro_api.scan_login(self.qr_code, self.verify_code)
            
            # 🚀 性能监控：记录scanLogin完成
            if PERF_MONITOR_AVAILABLE and perf_monitor.current_scan:
                perf_monitor.mark_api_scanlogin_done()
            
            if scan_result.get("code") == 200:
                self.log_message.emit("✓ 登录成功！")
                self.scan_result.emit({"success": True, "message": "登录成功"})
                
                # 🚀 性能监控：扫码成功
                if PERF_MONITOR_AVAILABLE:
                    perf_monitor.end_scan(success=True)
                    # 输出性能报告
                    summary = perf_monitor.get_last_scan_summary()
                    self.log_message.emit("\n" + summary)
            elif scan_result.get("code") == 2240:
                # 需要短信验证码
                self.log_message.emit("⚠ 需要短信验证码")
                self.scan_result.emit({"success": False, "message": "需要短信验证码", "need_sms": True})
            else:
                # 如果有验证码但失败了，尝试不带验证码再登录一次
                if self.verify_code:
                    scan_result_retry = kuro_api.scan_login(self.qr_code, "")
                    if scan_result_retry.get("code") == 200:
                        self.log_message.emit("✓ 登录成功！")
                        self.scan_result.emit({"success": True, "message": "登录成功"})
                    else:
                        msg = scan_result_retry.get("msg", "登录失败")
                        self.log_message.emit(f"❌ {msg}")
                        self.scan_result.emit({"success": False, "message": msg})
                else:
                    msg = scan_result.get("msg", "扫码失败")
                    self.log_message.emit(f"❌ {msg}")
                    self.scan_result.emit({"success": False, "message": msg})
                
        except Exception as e:
            self.log_message.emit(f"❌ {str(e)}")
            self.scan_result.emit({"success": False, "message": str(e)})
            if PERF_MONITOR_AVAILABLE:
                perf_monitor.end_scan(success=False)


class MainWindow(QMainWindow):
    """主窗口"""
    
    def __init__(self):
        super().__init__()
        self.setWindowTitle("鸣潮抢码器 v1.0 - 极速版")
        self.setFixedSize(600, 820)  # 增加高度以容纳所有内容
        
        # 设置程序图标
        icon_path = "11409B.png"
        # 打包后图标在根目录
        if not os.path.exists(icon_path) and hasattr(sys, '_MEIPASS'):
            icon_path = os.path.join(sys._MEIPASS, '11409B.png')
        if os.path.exists(icon_path):
            from PySide6.QtGui import QIcon
            self.setWindowIcon(QIcon(icon_path))
        
        self.scan_window = None
        self.scan_thread = None
        self.live_scanner = None  # 🎥 直播流扫描器
        self.pending_qr_code = None
        
        self.setup_ui()
        self.apply_styles()
        self.load_user_info()
    
    def setup_ui(self):
        """设置 UI"""
        # 中央部件
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        # 主布局
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(15)
        main_layout.setContentsMargins(20, 20, 20, 20)
        
        # 标题
        title = QLabel("鸣潮抢码器")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont("PingFang SC", 22)
        title_font.setBold(True)
        title.setFont(title_font)
        main_layout.addWidget(title)
        
        # 用户信息区域
        self.setup_user_info_section(main_layout)
        
        # 控制按钮区域
        self.setup_control_section(main_layout)
        
        # 日志区域
        self.setup_log_section(main_layout)
    
    def setup_user_info_section(self, parent_layout):
        """设置用户信息区域"""
        info_widget = QWidget()
        info_widget.setObjectName("infoWidget")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setSpacing(10)
        info_layout.setContentsMargins(15, 15, 15, 15)
        
        # 标题
        info_title = QLabel("账号信息")
        info_title_font = QFont("PingFang SC", 14)
        info_title_font.setBold(True)
        info_title.setFont(info_title_font)
        info_layout.addWidget(info_title)
        
        # UID
        self.uid_label = QLabel("UID: 未登录")
        info_layout.addWidget(self.uid_label)
        
        # Token
        self.token_label = QLabel("Token: 未登录")
        info_layout.addWidget(self.token_label)
        
        # 登录按钮
        self.login_btn = QPushButton("登录账号")
        self.login_btn.setObjectName("loginBtn")
        self.login_btn.setFixedHeight(45)
        self.login_btn.clicked.connect(self.on_login_clicked)
        info_layout.addWidget(self.login_btn)
        
        parent_layout.addWidget(info_widget)
    
    def setup_control_section(self, parent_layout):
        """设置控制按钮区域"""
        control_widget = QWidget()
        control_widget.setObjectName("controlWidget")
        control_layout = QVBoxLayout(control_widget)
        control_layout.setSpacing(10)
        control_layout.setContentsMargins(15, 15, 15, 15)
        
        # 标题
        control_title = QLabel("扫码控制")
        control_title_font = QFont("PingFang SC", 14)
        control_title_font.setBold(True)
        control_title.setFont(control_title_font)
        control_layout.addWidget(control_title)
        
        # 按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        
        # 开始扫码按钮
        self.start_scan_btn = QPushButton("开始扫码")
        self.start_scan_btn.setFixedHeight(50)
        self.start_scan_btn.clicked.connect(self.on_start_scan)
        btn_layout.addWidget(self.start_scan_btn)
        
        # 停止扫码按钮
        self.stop_scan_btn = QPushButton("停止扫码")
        self.stop_scan_btn.setObjectName("stopBtn")
        self.stop_scan_btn.setFixedHeight(50)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.clicked.connect(self.on_stop_scan)
        btn_layout.addWidget(self.stop_scan_btn)
        
        control_layout.addLayout(btn_layout)
        
        # 🚀 选项区域（放在独立的垂直布局中）
        from PySide6.QtWidgets import QCheckBox, QLineEdit
        
        options_layout = QVBoxLayout()
        options_layout.setSpacing(10)
        options_layout.setContentsMargins(0, 10, 0, 10)
        
        # 多线程选项
        self.thread_pool_checkbox = QCheckBox("启用多线程池加速（实验性）")
        self.thread_pool_checkbox.setChecked(config_manager.get("thread_pool_enabled", False))
        self.thread_pool_checkbox.setToolTip("启用多线程并行处理图像增强\n适用于复杂场景，单个QR码场景建议关闭")
        self.thread_pool_checkbox.stateChanged.connect(self.on_thread_pool_changed)
        options_layout.addWidget(self.thread_pool_checkbox)
        
        # 自动登录选项
        self.auto_login_checkbox = QCheckBox("检测到二维码后自动登录")
        self.auto_login_checkbox.setChecked(config_manager.get("auto_login", False))
        self.auto_login_checkbox.setToolTip("启用后检测到QR码会立即登录，无需手动确认")
        self.auto_login_checkbox.stateChanged.connect(self.on_auto_login_changed)
        options_layout.addWidget(self.auto_login_checkbox)
        
        control_layout.addLayout(options_layout)
        
        # 🚀 自动重试功能默认启用（不显示选项，始终开启）
        config_manager.set("auto_retry", True)
        
        # 🎥 抖音直播流扫描区域
        live_layout = QHBoxLayout()
        
        self.live_room_input = QLineEdit()
        self.live_room_input.setPlaceholderText("抖音直播间ID或分享链接")
        self.live_room_input.setFixedHeight(40)
        self.live_room_input.setToolTip("输入抖音直播间ID（如：7318296342388083201）\n或粘贴分享链接（会自动提取ID）")
        live_layout.addWidget(self.live_room_input, 3)
        
        self.start_live_btn = QPushButton("扫描抖音直播")
        self.start_live_btn.setFixedHeight(40)
        self.start_live_btn.setToolTip("从抖音直播流中扫描QR码（适合直播间抢码）")
        self.start_live_btn.clicked.connect(self.on_start_live_scan)
        live_layout.addWidget(self.start_live_btn, 1)
        
        control_layout.addLayout(live_layout)
        
        # 状态标签
        self.status_label = QLabel("状态: 待机中")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        status_font = QFont("PingFang SC", 11)
        self.status_label.setFont(status_font)
        control_layout.addWidget(self.status_label)
        
        parent_layout.addWidget(control_widget)
    
    def setup_log_section(self, parent_layout):
        """设置日志区域"""
        log_widget = QWidget()
        log_widget.setObjectName("logWidget")
        log_layout = QVBoxLayout(log_widget)
        log_layout.setSpacing(10)
        log_layout.setContentsMargins(15, 15, 15, 15)
        
        # 标题
        log_title = QLabel("运行日志")
        log_title_font = QFont("PingFang SC", 14)
        log_title_font.setBold(True)
        log_title.setFont(log_title_font)
        log_layout.addWidget(log_title)
        
        # 先创建日志文本框
        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(220)  # 增加最小高度确保内容可见
        
        # 然后创建按钮（放在标题下面，但在添加到布局之前）
        log_btn_layout = QHBoxLayout()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.setObjectName("clearBtn")
        clear_log_btn.setFixedHeight(38)
        clear_log_btn.clicked.connect(self.log_text.clear)  # 现在 log_text 已经存在了
        log_btn_layout.addWidget(clear_log_btn)
        
        # 🚀 Performance stats button
        if PERF_MONITOR_AVAILABLE:
            perf_btn = QPushButton("📊 性能统计")
            perf_btn.setObjectName("perfBtn")
            perf_btn.setFixedHeight(38)
            perf_btn.clicked.connect(self.show_performance_stats)
            log_btn_layout.addWidget(perf_btn)
        
        # 按钮布局添加到主布局
        log_layout.addLayout(log_btn_layout)
        
        # 日志文本框添加到主布局（显示在按钮下面）
        log_layout.addWidget(self.log_text)
        
        parent_layout.addWidget(log_widget)
        
        # 初始日志
        self.add_log("🚀 鸣潮抢码器 v1.0 - 终极优化版")
        self.add_log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self.add_log("✓ DXGI GPU加速截图")
        self.add_log("✓ WeChat QR识别器")
        self.add_log("✓ 并行多候选识别（3线程）")
        self.add_log("✓ 智能ROI区域预测")
        self.add_log("✓ 内存池复用技术")
        self.add_log("✓ SIMD向量化处理")
        self.add_log("✓ 智能阶梯式重试（0.5s->1.0s->2.0s）")
        self.add_log("✓ 组件预热机制")
        self.add_log("✓ 性能监控系统")
        self.add_log("✓ Ticket去重机制（防止重复提交）")
        self.add_log("✓ API超时：roleInfos=800ms, scanLogin=1.2s")
        self.add_log("✓ QThreadPool多线程（16线程，可选启用）")
        self.add_log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        
        # 🚀 加载保存的配置
        self._load_saved_config()
        
        # 自动重试始终启用（隐式功能）
        self.add_log("✓ 自动重试已启用（二维码过期后自动继续扫描）")
        
        # 显示AI模型加载状态（包含详细调试信息）
        try:
            from utils.ai_qr_scanner import ai_qr_scanner
            
            # 显示所有加载消息（调试）
            if hasattr(ai_qr_scanner, 'load_messages'):
                for msg in ai_qr_scanner.load_messages:
                    self.add_log(msg)
            
            # 显示最终状态
            if ai_qr_scanner.ai_enabled:
                ai_status = []
                if ai_qr_scanner.sr_net is not None:
                    ai_status.append("超分辨率")
                if ai_qr_scanner.detect_net is not None:
                    ai_status.append("QR检测")
                
                if ai_status:
                    self.add_log(f"🤖 AI模型已加载: {', '.join(ai_status)}")
                    self.add_log("⚡ 极速优化版（直播间抢码专用）")
                    
                    # 显示QR识别器类型
                    if ai_qr_scanner.wechat_detector:
                        self.add_log("⚡ 微信QR识别器已启用")
                    else:
                        self.add_log("⚡ pyzbar识别器（推荐opencv-contrib）")
                    
                    # 显示截图方式
                    if ai_qr_scanner.dxgi_screenshot:
                        self.add_log("⚡ DXGI截图已启用（GPU加速）")
                    elif ai_qr_scanner.fast_screenshot:
                        self.add_log("⚡ BitBlt快速截图（比PIL快5-10倍）")
                    else:
                        self.add_log("⚡ PIL截图（推荐安装dxcam加速）")
                    
                    self.add_log("⚡ 智能分辨率识别（自动优化）")
                    self.add_log("⚡ Ticket去重机制（防止重复提交）")
                    
                    # 显示多线程池状态
                    if ai_qr_scanner.thread_pool:
                        workers = ai_qr_scanner.thread_pool.max_thread_count()
                        self.add_log(f"⚡ QThreadPool多线程池（{workers}线程，可选启用）")
                    
                    self.add_log("⚡ API超时: roleInfos=800ms, scanLogin=1.2s")
                else:
                    self.add_log("⚠️ AI模型未加载（使用传统算法）")
            else:
                self.add_log("⚠️ AI模型未启用（使用传统算法）")
        except Exception as e:
            import traceback
            self.add_log(f"⚠️ AI扫描器加载失败: {str(e)}")
            self.add_log(f"详细错误: {traceback.format_exc()}")
        
        self.add_log("请先登录账号，然后点击【开始扫码】")
    
    def apply_styles(self):
        """应用iOS风格样式"""
        self.setStyleSheet("""
            QMainWindow {
                background-color: #F5F5F7;
            }
            
            QWidget#infoWidget, QWidget#controlWidget, QWidget#logWidget {
                background-color: #FFFFFF;
                border-radius: 16px;
                border: 1px solid #E5E5EA;
            }
            
            QLabel {
                color: #1D1D1F;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            
            QPushButton {
                padding: 12px 24px;
                border: none;
                border-radius: 12px;
                background-color: #007AFF;
                color: #FFFFFF;
                font-size: 14px;
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
                background-color: #E5E5EA;
                color: #8E8E93;
            }
            
            /* 登录按钮特殊样式 */
            QPushButton#loginBtn {
                background-color: #34C759;
            }
            
            QPushButton#loginBtn:hover {
                background-color: #30B350;
            }
            
            QPushButton#loginBtn:pressed {
                background-color: #2A9F47;
            }
            
            /* 停止按钮特殊样式 */
            QPushButton#stopBtn {
                background-color: #FF3B30;
            }
            
            QPushButton#stopBtn:hover {
                background-color: #FF2D20;
            }
            
            QPushButton#stopBtn:pressed {
                background-color: #E02820;
            }
            
            /* 清空日志按钮 */
            QPushButton#clearBtn {
                background-color: #E5E5EA;
                color: #007AFF;
            }
            
            QPushButton#clearBtn:hover {
                background-color: #D1D1D6;
            }
            
            QTextEdit {
                background-color: #F5F5F7;
                color: #1D1D1F;
                border: 1px solid #D2D2D7;
                border-radius: 12px;
                padding: 12px;
                font-size: 13px;
                font-family: "PingFang SC", "Microsoft YaHei", "Consolas", monospace;
            }
            
            /* 状态标签特殊样式 */
            QLabel#statusLabel {
                color: #8E8E93;
                font-size: 13px;
                padding: 8px;
                background-color: #F5F5F7;
                border-radius: 8px;
            }
            
            /* 复选框样式 */
            QCheckBox {
                color: #1D1D1F;
                font-size: 13px;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
                spacing: 6px;
                min-height: 24px;
            }
            
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                border-radius: 4px;
                border: 1.5px solid #D2D2D7;
                background-color: #FFFFFF;
            }
            
            QCheckBox::indicator:hover {
                border-color: #007AFF;
            }
            
            QCheckBox::indicator:checked {
                background-color: #007AFF;
                border-color: #007AFF;
                image: url(data:image/svg+xml;base64,PHN2ZyB3aWR0aD0iMTAiIGhlaWdodD0iOCIgdmlld0JveD0iMCAwIDEwIDgiIGZpbGw9Im5vbmUiIHhtbG5zPSJodHRwOi8vd3d3LnczLm9yZy8yMDAwL3N2ZyI+PHBhdGggZD0iTTEgM0wzLjUgNi41TDkgMSIgc3Ryb2tlPSJ3aGl0ZSIgc3Ryb2tlLXdpZHRoPSIxLjgiIHN0cm9rZS1saW5lY2FwPSJyb3VuZCIgc3Ryb2tlLWxpbmVqb2luPSJyb3VuZCIvPjwvc3ZnPg==);
            }
            
            QCheckBox:disabled {
                color: #8E8E93;
            }
            
            QCheckBox::indicator:disabled {
                border-color: #E5E5EA;
                background-color: #F5F5F7;
            }
            
            /* 输入框样式 */
            QLineEdit {
                background-color: #F5F5F7;
                color: #1D1D1F;
                border: 1px solid #D2D2D7;
                border-radius: 10px;
                padding: 10px 14px;
                font-size: 14px;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            
            QLineEdit:focus {
                border-color: #007AFF;
                background-color: #FFFFFF;
            }
            
            QLineEdit:disabled {
                background-color: #E5E5EA;
                color: #8E8E93;
            }
        """)
    
    def load_user_info(self):
        """加载用户信息"""
        uid = config_manager.get("uid", "")
        token = config_manager.get("token", "")
        
        if uid and token:
            self.uid_label.setText(f"UID: {uid[:6]}...{uid[-6:]}")
            self.token_label.setText(f"Token: {token[:10]}...{token[-10:]}")
            kuro_api.set_token(token)
            self.add_log("✓ 已加载保存的登录信息")
        else:
            self.uid_label.setText("UID: 未登录")
            self.token_label.setText("Token: 未登录")
    
    def on_login_clicked(self):
        """登录按钮点击"""
        try:
            self.add_log("正在打开登录对话框...")
            dialog = LoginDialog(self)
            dialog.login_success.connect(self.on_login_success)
            dialog.exec()
        except Exception as e:
            self.add_log(f"❌ 打开登录对话框失败: {str(e)}")
            import traceback
            self.add_log(traceback.format_exc())
    
    def on_login_success(self, data):
        """登录成功"""
        uid = data.get("userId", "")
        token = data.get("token", "")
        
        # 保存登录信息
        config_manager.update({
            "uid": uid,
            "token": token,
            "last_login_success": True
        })
        
        # 设置 token
        kuro_api.set_token(token)
        
        # 更新显示
        self.uid_label.setText(f"UID: {uid[:6]}...{uid[-6:]}")
        self.token_label.setText(f"Token: {token[:10]}...{token[-10:]}")
        
        self.add_log(f"✓ 登录成功！UID: {uid}")
    
    def on_start_scan(self):
        """开始扫码"""
        # 检查是否已登录
        if not config_manager.get("token"):
            QMessageBox.warning(self, "提示", "请先登录账号！")
            return
        
        # 🚀 预热网络连接（提前建立TCP连接，节省100-300ms）
        kuro_api.warm_up_connection()
        
        # 创建扫描窗口
        if not self.scan_window:
            self.scan_window = ScanWindow()
            self.scan_window.qr_detected.connect(self.on_qr_detected)
        
        self.scan_window.show()
        self.scan_window.start_scanning()
        
        # 更新按钮状态
        self.start_scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.status_label.setText("状态: 扫描中...")
        
        self.add_log("开始扫描...")
    
    def on_stop_scan(self):
        """停止扫码"""
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        
        # 更新按钮状态
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_label.setText("状态: 待机中")
        
        self.add_log("已停止扫描")
    
    def on_thread_pool_changed(self, state):
        """多线程池开关改变"""
        try:
            from utils.ai_qr_scanner import ai_qr_scanner
            if state:
                ai_qr_scanner.use_thread_pool = True
                self.add_log("✓ 已启用多线程池")
                if ai_qr_scanner.thread_pool:
                    workers = ai_qr_scanner.thread_pool.max_thread_count()
                    self.add_log(f"✓ 线程池配置: {workers}个工作线程（自动检测CPU核心数）")
            else:
                ai_qr_scanner.use_thread_pool = False
                self.add_log("✓ 已禁用多线程池（单线程模式）")
            
            # 保存配置
            config_manager.set("thread_pool_enabled", bool(state))
        except Exception as e:
            self.add_log(f"⚠️ 多线程池切换失败: {e}")
    
    def on_auto_login_changed(self, state):
        """自动登录开关改变"""
        config_manager.set("auto_login", bool(state))
        if state:
            self.add_log("✓ 已启用自动登录（检测到QR码立即登录）")
        else:
            self.add_log("✓ 已禁用自动登录（需要手动确认）")
    
    def _load_saved_config(self):
        """加载保存的配置"""
        try:
            # 加载多线程池设置
            if hasattr(self, 'thread_pool_checkbox'):
                thread_pool_enabled = config_manager.get("thread_pool_enabled", False)
                self.thread_pool_checkbox.setChecked(thread_pool_enabled)
                
                # 同步到AI扫描器
                try:
                    from utils.ai_qr_scanner import ai_qr_scanner
                    ai_qr_scanner.use_thread_pool = thread_pool_enabled
                except:
                    pass
            
            # 加载自动登录设置
            if hasattr(self, 'auto_login_checkbox'):
                auto_login = config_manager.get("auto_login", False)
                self.auto_login_checkbox.setChecked(auto_login)
            
            # 加载上次登录的token
            last_token = config_manager.get("token", "")
            last_uid = config_manager.get("uid", "")
            last_login_success = config_manager.get("last_login_success", False)
            
            if last_login_success and last_token and last_uid:
                # 设置token
                kuro_api.set_token(last_token)
                
                # 更新UI显示
                self.uid_label.setText(f"UID: {last_uid[:6]}...{last_uid[-6:]}")
                self.token_label.setText(f"Token: {last_token[:10]}...{last_token[-10:]}")
                
                self.add_log("✓ 已加载保存的登录信息")
            
            # 加载多线程池设置
            if config_manager.get("thread_pool_enabled", False):
                try:
                    from utils.ai_qr_scanner import ai_qr_scanner
                    ai_qr_scanner.use_thread_pool = True
                except:
                    pass
        except Exception as e:
            print(f"[Config] Failed to load saved config: {e}")
    
    def extract_douyin_room_id(self, text: str) -> str:
        """
        从抖音分享链接或文本中提取房间ID
        
        支持格式：
        1. 直接的房间ID：7318296342388083201
        2. 分享链接：https://v.douyin.com/xxx/
        3. 带roomid的链接：https://live.douyin.com/123456
        """
        import re
        
        # 如果是纯数字，直接返回
        if text.isdigit() and len(text) >= 10:
            return text
        
        # 尝试从URL中提取roomid参数
        # 例如：https://webcast.amemv.com/douyin/webcast/reflow/xxx?room_id=7318296342388083201
        room_id_match = re.search(r'room_id=(\d+)', text)
        if room_id_match:
            return room_id_match.group(1)
        
        # 尝试从直播间链接提取
        # 例如：https://live.douyin.com/7318296342388083201
        live_match = re.search(r'live\.douyin\.com/(\d+)', text)
        if live_match:
            return live_match.group(1)
        
        # 尝试提取任何长数字串（10位以上）
        long_num_match = re.search(r'\d{10,}', text)
        if long_num_match:
            return long_num_match.group(0)
        
        return ""
    
    def on_start_live_scan(self):
        """开始抖音直播流扫描"""
        # 检查是否已登录
        if not kuro_api.token:
            self.add_log("❌ 请先登录账号")
            return
        
        # 获取输入文本
        input_text = self.live_room_input.text().strip()
        if not input_text:
            self.add_log("❌ 请输入抖音直播间ID或分享链接")
            QMessageBox.warning(self, "警告", "请输入抖音直播间ID或分享链接！")
            return
        
        # 提取房间ID
        room_id = self.extract_douyin_room_id(input_text)
        if not room_id:
            self.add_log("❌ 无法识别的房间ID格式")
            QMessageBox.warning(self, "警告", 
                              "无法识别的房间ID格式！\n\n"
                              "支持格式：\n"
                              "1. 直接输入房间ID（如：7318296342388083201）\n"
                              "2. 粘贴抖音分享链接\n"
                              "3. 直播间完整URL")
            return
        
        self.add_log(f"✓ 提取到房间ID: {room_id}")
        
        # 停止屏幕扫描
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        
        # 停止之前的直播流扫描
        if self.live_scanner and self.live_scanner.isRunning():
            self.live_scanner.stop()
            self.live_scanner.wait()
        
        # 创建直播流扫描器
        try:
            from utils.live_stream_scanner import get_live_stream_scanner
            self.live_scanner = get_live_stream_scanner()
            
            # 连接信号
            self.live_scanner.qr_detected.connect(self.on_qr_detected)
            self.live_scanner.status_changed.connect(self.add_log)
            self.live_scanner.error_occurred.connect(lambda msg: self.add_log(f"❌ {msg}"))
            
            # 设置流地址并启动（只支持抖音）
            self.live_scanner.set_stream_url(room_id, "douyin")
            self.live_scanner.start()
            
            self.add_log(f"🎥 开始扫描抖音直播间: {room_id}")
            self.status_label.setText("状态: 抖音直播流扫描中...")
            
            # 更新按钮状态
            self.start_scan_btn.setEnabled(False)
            self.start_live_btn.setText("停止直播扫描")
            self.start_live_btn.clicked.disconnect()
            self.start_live_btn.clicked.connect(self.on_stop_live_scan)
            
        except Exception as e:
            self.add_log(f"❌ 启动直播流扫描失败: {e}")
    
    def on_stop_live_scan(self):
        """停止抖音直播流扫描"""
        if self.live_scanner:
            self.live_scanner.stop()
            self.add_log("✓ 已停止抖音直播流扫描")
        
        self.status_label.setText("状态: 待机中")
        self.start_scan_btn.setEnabled(True)
        self.start_live_btn.setText("扫描抖音直播")
        self.start_live_btn.clicked.disconnect()
        self.start_live_btn.clicked.connect(self.on_start_live_scan)
    
    def on_qr_detected(self, qr_code):
        """⚡ 检测到二维码 - 自动确认模式"""
        self.add_log(f"✓ 检测到二维码，正在登录...")
        
        # 保存待处理的二维码
        self.pending_qr_code = qr_code
        
        # 先关闭扫描窗口（红框消失）
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        
        # 更新按钮状态
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_label.setText("状态: 登录中...")
        
        # 开始扫码线程（必须保留roleInfos验证）
        self.scan_thread = ScanThread(qr_code, skip_role_check=False)
        self.scan_thread.scan_result.connect(self.on_scan_result)
        self.scan_thread.log_message.connect(self.add_log)
        self.scan_thread.start()
    
    def on_scan_result(self, result):
        """扫码结果"""
        if result.get("success"):
            self.add_log("🎉 扫码成功！手机已确认，登录完成！")
            self.status_label.setText("状态: 登录成功")
            QMessageBox.information(self, "成功", "扫码登录成功！\n\n已在手机上确认登录")
            # 成功后确保扫描窗口已关闭
            if self.scan_window:
                self.scan_window.close()
                self.scan_window = None
            self.start_scan_btn.setEnabled(True)
            self.stop_scan_btn.setEnabled(False)
        elif result.get("need_sms"):
            # 需要手机端确认验证
            self.add_log("⚠ 检测到需要手机端确认（首次使用此账号扫码）")
            
            # 询问用户是否发送验证码
            reply = QMessageBox.question(
                self,
                "需要验证",
                "这是首次使用此账号扫码，需要短信验证码确认。\n\n"
                "是否发送验证码到手机？\n\n"
                "提示：验证成功后，之后的扫码将不再需要验证码",
                QMessageBox.Yes | QMessageBox.No,
                QMessageBox.Yes
            )
            
            if reply == QMessageBox.No:
                self.add_log("❌ 用户取消验证")
                self.status_label.setText("状态: 已取消")
                return
            
            self.add_log("正在发送验证码到手机...")
            
            # 发送短信验证码
            sms_result = kuro_api.send_sms()
            if sms_result.get("code") == 200:
                self.add_log("✓ 验证码已发送到手机")
                
                # 自动弹出输入框
                code, ok = QInputDialog.getText(
                    self,
                    "手机验证",
                    "请输入手机收到的验证码:",
                    QLineEdit.EchoMode.Normal,
                    ""
                )
            else:
                # 发送失败，但仍然允许输入之前收到的验证码
                error_msg = sms_result.get('msg', '未知错误')
                self.add_log(f"❌ 发送验证码失败: {error_msg}")
                self.add_log("💡 如果您之前已收到验证码，可以直接输入")
                
                # 直接弹出输入框
                code, ok = QInputDialog.getText(
                    self,
                    "手机验证",
                    f"发送验证码失败: {error_msg}\n\n"
                    "如果您之前已收到验证码，请输入:\n"
                    "（或点击取消，等待5-10分钟后重试）",
                    QLineEdit.EchoMode.Normal,
                    ""
                )
                
            
            if ok and code:
                self.add_log(f"收到验证码，重新执行扫码登录...")
                # 重新扫码，带上验证码，跳过二维码验证（避免过期）
                self.scan_thread = ScanThread(self.pending_qr_code, skip_role_check=True)
                self.scan_thread.verify_code = code
                self.scan_thread.scan_result.connect(self.on_scan_result)
                self.scan_thread.log_message.connect(self.add_log)
                self.scan_thread.start()
            else:
                self.add_log("❌ 用户取消输入验证码")
                self.status_label.setText("状态: 已取消")
                # 重置扫描窗口状态
                if self.scan_window:
                    self.scan_window.reset_processing()
        else:
            message = result.get("message", "未知错误")
            self.add_log(f"❌ 扫码失败: {message}")
            
            # 🚀 自动重试逻辑 - 二维码过期后自动继续扫描
            if "二维码已过期" in message or "二维码已失效" in message:
                auto_retry = config_manager.get("auto_retry", True)
                if auto_retry and self.scan_window and not self.scan_window.isHidden():
                    self.add_log("⚡ 二维码已过期，3秒后自动重试...")
                    # 重置扫描窗口的ticket缓存，允许重新扫描
                    if hasattr(self.scan_window, 'last_ticket'):
                        self.scan_window.last_ticket = ""
                    # 3秒后自动重新开始扫描
                    QTimer.singleShot(3000, lambda: self.auto_retry_scan())
                    return
            
            if "Token已过期" in message:
                QMessageBox.warning(self, "提示", "登录已过期，请重新登录账号！")
            
            # 重置扫描窗口状态（非自动重试情况）
            if self.scan_window:
                self.scan_window.reset_processing()
    
    def auto_retry_scan(self):
        """自动重试扫描（二维码过期后触发）"""
        # 检查扫描窗口是否仍然打开
        if self.scan_window and not self.scan_window.isHidden():
            self.add_log("🔄 自动重试中...")
            # 扫描窗口应该仍在运行，只需要让它继续扫描即可
            # 不需要重新创建窗口，因为ticket已经被清空
        else:
            self.add_log("⚠ 扫描窗口已关闭，取消自动重试")
    
    def add_log(self, message):
        """添加日志"""
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        
        # 自动滚动到底部
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())
    
    def show_performance_stats(self):
        """显示性能统计信息"""
        if not PERF_MONITOR_AVAILABLE:
            QMessageBox.information(self, "性能统计", "性能监控系统未可用")
            return
        
        # 获取统计信息
        stats_summary = perf_monitor.get_statistics_summary()
        method_distribution = perf_monitor.get_method_distribution()
        
        # 获取内存池和ROI检测器统计
        extra_info = []
        
        try:
            from utils.image_buffer_pool import image_buffer_pool
            pool_stats = image_buffer_pool.get_stats()
            extra_info.append(f"内存池: {pool_stats['total_buffers']}个缓冲区, {pool_stats['total_memory_mb']}MB")
        except Exception:
            pass
        
        try:
            from utils.smart_roi_detector import smart_roi_detector
            roi_stats = smart_roi_detector.get_stats()
            extra_info.append(f"ROI预测: {roi_stats['accuracy']}% 准确率 ({roi_stats['successful_predictions']}/{roi_stats['total_predictions']})")
        except Exception:
            pass
        
        # 组合信息
        full_info = stats_summary + "\n\n" + method_distribution
        if extra_info:
            full_info += "\n\n" + "\n".join(extra_info)
        
        # 显示在日志中
        self.add_log("\n" + stats_summary)
        self.add_log(method_distribution)
        for info in extra_info:
            self.add_log(info)
        
        # 也显示在弹窗中
        QMessageBox.information(self, "性能统计", full_info)
    
    def closeEvent(self, event):
        """关闭事件"""
        if self.scan_window:
            self.scan_window.close()
        event.accept()

