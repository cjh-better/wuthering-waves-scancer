# -*- coding: utf-8 -*-
"""主窗口 — 竞品级功能（参考 KuRo_Scanner）"""
import os
import sys
import platform
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QInputDialog, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QMenu, QAbstractItemView,
)
from PySide6.QtGui import QFont, QIcon, QAction
from ui.login_dialog import LoginDialog
from ui.scan_window import ScanWindow
from ui.sms_dialog import SmsDialog
from utils.config_manager import config_manager
from utils.account_manager import account_manager
from utils.kuro_api import KuroAPI, kuro_api
from utils.qr_payload import extract_kuro_ticket

# 性能监控（可选）
try:
    from utils.performance_monitor import perf_monitor
    PERF_MONITOR_AVAILABLE = True
except Exception:
    PERF_MONITOR_AVAILABLE = False


# ======================================================================
# ScanThread
# ======================================================================

class ScanThread(QThread):
    """扫码线程"""

    scan_result = Signal(dict)
    log_message = Signal(str)

    def __init__(self, qr_code, parent=None, skip_role_check=False):
        super().__init__(parent)
        self.qr_code = qr_code
        self.verify_code = ""
        self.auto_login = False
        self.skip_role_check = skip_role_check

    def run(self):
        """执行扫码"""
        try:
            if not self.skip_role_check:
                role_result = kuro_api.get_role_infos(self.qr_code)
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

            scan_result = kuro_api.scan_login(
                self.qr_code, self.verify_code, self.auto_login,
            )
            if PERF_MONITOR_AVAILABLE and perf_monitor.current_scan:
                perf_monitor.mark_api_scanlogin_done()

            if scan_result.get("code") == 200:
                self.log_message.emit("✓ 登录成功！")
                self.scan_result.emit({"success": True, "message": "登录成功"})
                if PERF_MONITOR_AVAILABLE:
                    perf_monitor.end_scan(success=True)
                    summary = perf_monitor.get_last_scan_summary()
                    self.log_message.emit("\n" + summary)
            elif scan_result.get("code") == 2240:
                self.log_message.emit("⚠ 需要短信验证码")
                self.scan_result.emit({"success": False, "message": "需要短信验证码", "need_sms": True})
            else:
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


# ======================================================================
# AccountValidityThread — 扫描前异步检查账号有效性
# ======================================================================

class AccountValidityThread(QThread):
    """异步检查账号 token 是否仍然有效"""

    result = Signal(int, str, str)  # (row, status, message)

    def __init__(self, row: int, uid: str, token: str, parent=None):
        super().__init__(parent)
        self.row = row
        self.uid = uid
        self.token = token

    def run(self):
        try:
            checker = KuroAPI()
            checker.set_token(self.token)
            resp = checker.get_role_infos("CHECK", smart_retry=False)
            code = resp.get("code")
            if code == 220:
                self.result.emit(self.row, "过期", "Token已过期，请重新添加账号")
            elif code == -1:
                self.result.emit(self.row, "未知", resp.get("msg", "网络检查失败"))
            elif code == 200:
                self.result.emit(self.row, "可用", "")
            else:
                self.result.emit(self.row, "未知", resp.get("msg", "接口未返回明确状态"))
        except Exception as e:
            self.result.emit(self.row, "未知", f"检查账号状态失败: {e}")


# ======================================================================
# MainWindow
# ======================================================================

class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("鸣潮抢码器 v3.0 - Release")
        self.setFixedSize(680, 900)

        # 程序图标
        icon_path = "11409B.png"
        if not os.path.exists(icon_path) and hasattr(sys, "_MEIPASS"):
            icon_path = os.path.join(sys._MEIPASS, "11409B.png")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))

        # 状态变量
        self.scan_window = None
        self.scan_thread = None
        self.live_scanner = None
        self.pending_qr_code = None
        self.pending_ticket = ""
        self.login_in_progress = False
        self.account_check_threads = []
        self.selected_account_index = -1  # 当前选中的账号行

        self.setup_ui()
        self.apply_styles()
        self._load_accounts_to_table()
        self._load_saved_config()
        self._auto_start_if_configured()

    # ==================================================================
    # UI Setup
    # ==================================================================

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(12)
        main_layout.setContentsMargins(16, 16, 16, 16)

        # 标题
        title = QLabel("鸣潮抢码器")
        title.setAlignment(Qt.AlignCenter)
        title_font = QFont("PingFang SC", 22)
        title_font.setBold(True)
        title.setFont(title_font)
        main_layout.addWidget(title)

        self._setup_account_section(main_layout)
        self._setup_control_section(main_layout)
        self._setup_log_section(main_layout)

    # ------------------------------------------------------------------
    # 1. 多账号管理区域
    # ------------------------------------------------------------------

    def _setup_account_section(self, parent_layout):
        info_widget = QWidget()
        info_widget.setObjectName("infoWidget")
        info_layout = QVBoxLayout(info_widget)
        info_layout.setSpacing(8)
        info_layout.setContentsMargins(12, 12, 12, 12)

        # 标题行 + 添加账号按钮
        header = QHBoxLayout()
        info_title = QLabel("账号管理")
        info_title_font = QFont("PingFang SC", 14)
        info_title_font.setBold(True)
        info_title.setFont(info_title_font)
        header.addWidget(info_title)
        header.addStretch()

        add_btn = QPushButton("添加账号")
        add_btn.setObjectName("loginBtn")
        add_btn.setFixedHeight(36)
        add_btn.setFixedWidth(120)
        add_btn.clicked.connect(self.on_add_account)
        header.addWidget(add_btn)

        refresh_btn = QPushButton("刷新状态")
        refresh_btn.setFixedHeight(36)
        refresh_btn.setFixedWidth(100)
        refresh_btn.clicked.connect(self.refresh_account_statuses)
        header.addWidget(refresh_btn)
        info_layout.addLayout(header)

        # 当前选中账号显示
        self.selected_account_label = QLabel("当前账号: 未选中")
        self.selected_account_label.setFont(QFont("PingFang SC", 11))
        info_layout.addWidget(self.selected_account_label)

        # 账号表格
        self.account_table = QTableWidget(0, 5)
        self.account_table.setHorizontalHeaderLabels(["#", "UID", "昵称", "状态", "备注"])
        self.account_table.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Fixed)
        self.account_table.horizontalHeader().setSectionResizeMode(4, QHeaderView.Stretch)
        self.account_table.setColumnWidth(0, 35)
        self.account_table.setColumnWidth(1, 110)
        self.account_table.setColumnWidth(2, 110)
        self.account_table.setColumnWidth(3, 70)
        self.account_table.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.account_table.setSelectionMode(QAbstractItemView.SingleSelection)
        self.account_table.setMinimumHeight(100)
        self.account_table.setMaximumHeight(160)
        self.account_table.setContextMenuPolicy(Qt.CustomContextMenu)
        self.account_table.customContextMenuRequested.connect(self._show_account_context_menu)
        self.account_table.cellClicked.connect(self._on_account_selected)
        self.account_table.itemChanged.connect(self._on_note_edited)
        info_layout.addWidget(self.account_table)

        parent_layout.addWidget(info_widget)

    def _load_accounts_to_table(self):
        """将 AccountManager 中的账号加载到表格"""
        self.account_table.blockSignals(True)
        self.account_table.setRowCount(0)
        for i in range(account_manager.size()):
            self._insert_table_row(
                account_manager.get_account_uid(i),
                account_manager.get_account_name(i),
                account_manager.get_account_status(i),
                account_manager.get_account_note(i),
            )
        self.account_table.blockSignals(False)

        # 恢复上次选中的默认账号
        default_uid = config_manager.get("default_account", "")
        if default_uid:
            idx = account_manager.find_index_by_uid(default_uid)
            if idx is not None:
                self.selected_account_index = idx
                self.account_table.selectRow(idx)
                self._activate_account(idx)

    def _insert_table_row(self, uid: str, name: str, status: str, note: str):
        row = self.account_table.rowCount()
        self.account_table.insertRow(row)

        # #列（只读）
        idx_item = QTableWidgetItem(str(row + 1))
        idx_item.setFlags(idx_item.flags() & ~Qt.ItemIsEditable)
        self.account_table.setItem(row, 0, idx_item)

        # UID列（只读）
        uid_item = QTableWidgetItem(uid)
        uid_item.setFlags(uid_item.flags() & ~Qt.ItemIsEditable)
        self.account_table.setItem(row, 1, uid_item)

        # 昵称列（只读）
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemIsEditable)
        self.account_table.setItem(row, 2, name_item)

        # 状态列（只读）
        status_item = QTableWidgetItem(status or "未知")
        status_item.setFlags(status_item.flags() & ~Qt.ItemIsEditable)
        self.account_table.setItem(row, 3, status_item)

        # 备注列（可编辑）
        note_item = QTableWidgetItem(note)
        self.account_table.setItem(row, 4, note_item)

    def _on_note_edited(self, item: QTableWidgetItem):
        """备注列被编辑时同步到 AccountManager"""
        if item.column() == 4:
            account_manager.set_account_note(item.row(), item.text())

    def refresh_account_statuses(self):
        """异步刷新账号状态，避免阻塞主窗口。"""
        if account_manager.size() == 0:
            self.add_log("没有可刷新的账号")
            return
        self.add_log("开始刷新账号状态...")
        self.account_check_threads = [
            t for t in self.account_check_threads if t.isRunning()
        ]
        for row in range(account_manager.size()):
            account_manager.set_account_status(row, "检查中", "")
            self._update_account_status_cell(row, "检查中")
            thread = AccountValidityThread(
                row,
                account_manager.get_account_uid(row),
                account_manager.get_account_token(row),
                self,
            )
            thread.result.connect(self._on_account_status_checked)
            thread.finished.connect(lambda t=thread: self._discard_account_check_thread(t))
            self.account_check_threads.append(thread)
            thread.start()

    def _discard_account_check_thread(self, thread):
        if thread in self.account_check_threads:
            self.account_check_threads.remove(thread)

    def _update_account_status_cell(self, row: int, status: str):
        if 0 <= row < self.account_table.rowCount():
            item = self.account_table.item(row, 3)
            if item is None:
                item = QTableWidgetItem()
                item.setFlags(item.flags() & ~Qt.ItemIsEditable)
                self.account_table.setItem(row, 3, item)
            item.setText(status)

    def _on_account_status_checked(self, row: int, status: str, message: str):
        account_manager.set_account_status(row, status, message)
        self._update_account_status_cell(row, status)
        name = account_manager.get_account_name(row) or account_manager.get_account_uid(row)
        if message:
            self.add_log(f"{name}: {status} - {message}")
        else:
            self.add_log(f"{name}: {status}")

    def _on_account_selected(self, row: int, _col: int):
        self._activate_account(row)

    def _activate_account(self, index: int):
        """选中某个账号作为当前活跃账号"""
        if index < 0 or index >= account_manager.size():
            return
        self.selected_account_index = index
        name = account_manager.get_account_name(index)
        uid = account_manager.get_account_uid(index)
        token = account_manager.get_account_token(index)
        kuro_api.set_token(token)
        self.selected_account_label.setText(f"当前账号: {name} (UID: {uid})")
        self.add_log(f"✓ 已选中账号: {name}")

    def _show_account_context_menu(self, pos):
        """右键菜单：设为默认 / 删除"""
        menu = QMenu(self)
        set_default_action = QAction("设为默认账号", self)
        set_default_action.triggered.connect(self._set_default_account)
        menu.addAction(set_default_action)

        delete_action = QAction("删除账号", self)
        delete_action.triggered.connect(self._delete_account)
        menu.addAction(delete_action)

        menu.exec(self.account_table.viewport().mapToGlobal(pos))

    def _set_default_account(self):
        row = self._get_selected_row()
        if row == -1:
            QMessageBox.information(self, "提示", "没有选择任何账号")
            return
        uid = account_manager.get_account_uid(row)
        config_manager.set("default_account", uid)
        QMessageBox.information(
            self, "设置成功",
            "已将该账号设为默认\n"
            "勾选「启动时自动监视屏幕」将在下次启动时自动扫描并使用该账号",
        )

    def _delete_account(self):
        row = self._get_selected_row()
        if row == -1:
            QMessageBox.information(self, "提示", "没有选择任何账号")
            return
        name = account_manager.get_account_name(row)
        reply = QMessageBox.question(
            self, "删除确认", f"确定要删除账号\n{name}？",
            QMessageBox.Yes | QMessageBox.No,
        )
        if reply != QMessageBox.Yes:
            return

        # 如果删除的是默认账号，清除默认
        uid = account_manager.get_account_uid(row)
        if config_manager.get("default_account", "") == uid:
            config_manager.set("default_account", "")

        account_manager.delete_account(row)
        self._load_accounts_to_table()
        self.selected_account_index = -1
        self.selected_account_label.setText("当前账号: 未选中")
        self.add_log(f"已删除账号: {name}")

    def _get_selected_row(self) -> int:
        items = self.account_table.selectedItems()
        if not items:
            return -1
        return self.account_table.row(items[0])

    # ------------------------------------------------------------------
    # 2. 控制区域
    # ------------------------------------------------------------------

    def _setup_control_section(self, parent_layout):
        control_widget = QWidget()
        control_widget.setObjectName("controlWidget")
        control_layout = QVBoxLayout(control_widget)
        control_layout.setSpacing(8)
        control_layout.setContentsMargins(12, 12, 12, 12)

        control_title = QLabel("扫码控制")
        control_title_font = QFont("PingFang SC", 14)
        control_title_font.setBold(True)
        control_title.setFont(control_title_font)
        control_layout.addWidget(control_title)

        # 屏幕扫描按钮行
        btn_layout = QHBoxLayout()
        self.start_scan_btn = QPushButton("开始扫码")
        self.start_scan_btn.setFixedHeight(50)
        self.start_scan_btn.clicked.connect(self.on_start_scan)
        btn_layout.addWidget(self.start_scan_btn)

        self.stop_scan_btn = QPushButton("停止扫码")
        self.stop_scan_btn.setObjectName("stopBtn")
        self.stop_scan_btn.setFixedHeight(50)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.clicked.connect(self.on_stop_scan)
        btn_layout.addWidget(self.stop_scan_btn)
        control_layout.addLayout(btn_layout)

        # 选项复选框
        options_layout = QVBoxLayout()
        options_layout.setSpacing(6)
        options_layout.setContentsMargins(0, 6, 0, 6)

        self.thread_pool_checkbox = QCheckBox("启用多线程池加速（实验性）")
        self.thread_pool_checkbox.setChecked(config_manager.get("thread_pool_enabled", False))
        self.thread_pool_checkbox.stateChanged.connect(self.on_thread_pool_changed)
        options_layout.addWidget(self.thread_pool_checkbox)

        self.auto_login_checkbox = QCheckBox("检测到二维码后自动登录")
        self.auto_login_checkbox.setChecked(config_manager.get("auto_login", False))
        self.auto_login_checkbox.stateChanged.connect(self.on_auto_login_changed)
        options_layout.addWidget(self.auto_login_checkbox)

        self.auto_exit_checkbox = QCheckBox("扫码成功后自动退出")
        self.auto_exit_checkbox.setChecked(config_manager.get("auto_exit", False))
        self.auto_exit_checkbox.stateChanged.connect(self._on_auto_exit_changed)
        options_layout.addWidget(self.auto_exit_checkbox)

        self.auto_screen_checkbox = QCheckBox("启动时自动监视屏幕")
        self.auto_screen_checkbox.setChecked(config_manager.get("auto_screen", False))
        self.auto_screen_checkbox.stateChanged.connect(self._on_auto_screen_changed)
        options_layout.addWidget(self.auto_screen_checkbox)

        control_layout.addLayout(options_layout)

        # 自动重试始终开启
        config_manager.set("auto_retry", True, save=False)

        # 直播流扫描区域
        live_layout = QHBoxLayout()

        self.live_platform_combo = QComboBox()
        self.live_platform_combo.addItems(["抖音", "B站"])
        self.live_platform_combo.setFixedHeight(40)
        self.live_platform_combo.setFixedWidth(80)
        live_layout.addWidget(self.live_platform_combo)

        self.live_room_input = QLineEdit()
        self.live_room_input.setPlaceholderText("直播间ID或分享链接")
        self.live_room_input.setFixedHeight(40)
        live_layout.addWidget(self.live_room_input, 3)

        self.start_live_btn = QPushButton("扫描直播")
        self.start_live_btn.setFixedHeight(40)
        self.start_live_btn.clicked.connect(self.on_start_live_scan)
        live_layout.addWidget(self.start_live_btn, 1)

        control_layout.addLayout(live_layout)

        # 状态标签
        self.status_label = QLabel("状态: 待机中")
        self.status_label.setObjectName("statusLabel")
        self.status_label.setAlignment(Qt.AlignCenter)
        self.status_label.setFont(QFont("PingFang SC", 11))
        control_layout.addWidget(self.status_label)

        parent_layout.addWidget(control_widget)

    # ------------------------------------------------------------------
    # 3. 日志区域
    # ------------------------------------------------------------------

    def _setup_log_section(self, parent_layout):
        log_widget = QWidget()
        log_widget.setObjectName("logWidget")
        log_layout = QVBoxLayout(log_widget)
        log_layout.setSpacing(8)
        log_layout.setContentsMargins(12, 12, 12, 12)

        log_title = QLabel("运行日志")
        log_title_font = QFont("PingFang SC", 14)
        log_title_font.setBold(True)
        log_title.setFont(log_title_font)
        log_layout.addWidget(log_title)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(180)

        log_btn_layout = QHBoxLayout()
        clear_log_btn = QPushButton("清空日志")
        clear_log_btn.setObjectName("clearBtn")
        clear_log_btn.setFixedHeight(34)
        clear_log_btn.clicked.connect(self.log_text.clear)
        log_btn_layout.addWidget(clear_log_btn)

        if PERF_MONITOR_AVAILABLE:
            perf_btn = QPushButton("性能统计")
            perf_btn.setObjectName("perfBtn")
            perf_btn.setFixedHeight(34)
            perf_btn.clicked.connect(self.show_performance_stats)
            log_btn_layout.addWidget(perf_btn)

        log_layout.addLayout(log_btn_layout)
        log_layout.addWidget(self.log_text)
        parent_layout.addWidget(log_widget)

        # 启动日志
        self.add_log("鸣潮抢码器 v3.0 - Release")
        self.add_log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
        self.add_log("✓ 多账号管理（增删改查+JSON持久化）")
        self.add_log("✓ 抖音/B站双平台直播流扫描")
        self.add_log("✓ 短信验证专用对话框（60秒倒计时）")
        self.add_log("✓ 扫码成功自动退出 / 启动自动扫描")
        self.add_log("✓ 登录确认对话框 / 账号有效性预检")
        self.add_log("✓ DXGI GPU加速截图")
        self.add_log("✓ WeChat QR识别器")
        self.add_log("✓ 并行多候选识别（3线程）")
        self.add_log("✓ 智能ROI区域预测 + 内存池复用")
        self.add_log("✓ 智能阶梯式重试 + 组件预热")
        self.add_log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # AI模型状态
        self._log_ai_status()

    def _log_ai_status(self):
        try:
            from utils.ai_qr_scanner import ai_qr_scanner
            if hasattr(ai_qr_scanner, "load_messages"):
                for msg in ai_qr_scanner.load_messages:
                    self.add_log(msg)
            if ai_qr_scanner.ai_enabled:
                ai_status = []
                if ai_qr_scanner.sr_net is not None:
                    ai_status.append("超分辨率")
                if ai_qr_scanner.detect_net is not None:
                    ai_status.append("QR检测")
                if ai_status:
                    self.add_log(f"AI模型已加载: {', '.join(ai_status)}")
        except Exception:
            pass
        self.add_log("请先添加账号，选中后点击【开始扫码】")

    # ==================================================================
    # Styles
    # ==================================================================

    def apply_styles(self):
        self.setStyleSheet("""
            QMainWindow { background-color: #F5F5F7; }
            QWidget#infoWidget, QWidget#controlWidget, QWidget#logWidget {
                background-color: #FFFFFF; border-radius: 16px; border: 1px solid #E5E5EA;
            }
            QLabel { color: #1D1D1F; font-family: "PingFang SC", "Microsoft YaHei", sans-serif; }
            QPushButton {
                padding: 10px 20px; border: none; border-radius: 12px;
                background-color: #007AFF; color: #FFFFFF; font-size: 14px;
                font-weight: 600; font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QPushButton:hover { background-color: #0051D5; }
            QPushButton:pressed { background-color: #004FC4; }
            QPushButton:disabled { background-color: #E5E5EA; color: #8E8E93; }
            QPushButton#loginBtn { background-color: #34C759; }
            QPushButton#loginBtn:hover { background-color: #30B350; }
            QPushButton#stopBtn { background-color: #FF3B30; }
            QPushButton#stopBtn:hover { background-color: #FF2D20; }
            QPushButton#clearBtn { background-color: #E5E5EA; color: #007AFF; }
            QPushButton#clearBtn:hover { background-color: #D1D1D6; }
            QTextEdit {
                background-color: #F5F5F7; color: #1D1D1F; border: 1px solid #D2D2D7;
                border-radius: 12px; padding: 10px; font-size: 13px;
                font-family: "PingFang SC", "Microsoft YaHei", "Consolas", monospace;
            }
            QLabel#statusLabel {
                color: #8E8E93; font-size: 13px; padding: 6px;
                background-color: #F5F5F7; border-radius: 8px;
            }
            QCheckBox {
                color: #1D1D1F; font-size: 13px;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
                spacing: 6px; min-height: 22px;
            }
            QCheckBox::indicator {
                width: 16px; height: 16px; border-radius: 4px;
                border: 1.5px solid #D2D2D7; background-color: #FFFFFF;
            }
            QCheckBox::indicator:hover { border-color: #007AFF; }
            QCheckBox::indicator:checked {
                background-color: #007AFF; border-color: #007AFF;
            }
            QLineEdit {
                background-color: #F5F5F7; color: #1D1D1F; border: 1px solid #D2D2D7;
                border-radius: 10px; padding: 10px 14px; font-size: 14px;
                font-family: "PingFang SC", "Microsoft YaHei", sans-serif;
            }
            QLineEdit:focus { border-color: #007AFF; background-color: #FFFFFF; }
            QLineEdit:disabled { background-color: #E5E5EA; color: #8E8E93; }
            QTableWidget {
                background-color: #FFFFFF; border: 1px solid #D2D2D7; border-radius: 8px;
                font-size: 13px; gridline-color: #E5E5EA;
            }
            QTableWidget::item:selected { background-color: #007AFF; color: #FFFFFF; }
            QHeaderView::section {
                background-color: #F5F5F7; border: none; border-bottom: 1px solid #D2D2D7;
                padding: 6px; font-weight: 600; font-size: 12px;
            }
            QComboBox {
                background-color: #F5F5F7; border: 1px solid #D2D2D7;
                border-radius: 10px; padding: 8px 12px; font-size: 14px;
            }
            QComboBox:focus { border-color: #007AFF; }
            QComboBox::drop-down { border: none; width: 24px; }
        """)

    # ==================================================================
    # Account Actions
    # ==================================================================

    def on_add_account(self):
        """添加账号（打开登录对话框）"""
        if (self.scan_window and self.scan_window.isVisible()) or \
           (self.live_scanner and self.live_scanner.isRunning()):
            QMessageBox.information(self, "提示", "请先停止扫描！")
            return
        dialog = LoginDialog(self)
        dialog.login_success.connect(self._on_login_success_add_account)
        dialog.exec()

    def _on_login_success_add_account(self, data):
        """登录成功后添加账号"""
        uid = data.get("userId", "")
        token = data.get("token", "")
        name = data.get("userName", uid)
        mobile = data.get("mobile", "")

        if account_manager.has_uid(uid):
            # 已存在 → 更新 token
            idx = account_manager.find_index_by_uid(uid)
            if idx is not None:
                account_manager.update_account_token(idx, token)
                self.add_log(f"✓ 账号已存在，已更新Token: {name}")
                self._activate_account(idx)
            return

        account_manager.add_account(name, uid, token, mobile)
        self._load_accounts_to_table()
        new_idx = account_manager.size() - 1
        self.account_table.selectRow(new_idx)
        self._activate_account(new_idx)
        self.add_log(f"✓ 添加账号成功: {name} (UID: {uid})")

    # ==================================================================
    # Config Checkbox Handlers
    # ==================================================================

    def on_thread_pool_changed(self, state):
        try:
            from utils.ai_qr_scanner import ai_qr_scanner
            ai_qr_scanner.use_thread_pool = bool(state)
        except Exception:
            pass
        config_manager.set("thread_pool_enabled", bool(state))

    def on_auto_login_changed(self, state):
        config_manager.set("auto_login", bool(state))

    def _on_auto_exit_changed(self, state):
        config_manager.set("auto_exit", bool(state))

    def _on_auto_screen_changed(self, state):
        if state and not config_manager.get("default_account", ""):
            self.auto_screen_checkbox.setChecked(False)
            QMessageBox.information(self, "提示", "请先右键账号设为默认账号！")
            return
        config_manager.set("auto_screen", bool(state))

    def _load_saved_config(self):
        """加载已保存的配置到 UI"""
        try:
            self.thread_pool_checkbox.setChecked(config_manager.get("thread_pool_enabled", False))
            self.auto_login_checkbox.setChecked(config_manager.get("auto_login", False))
            self.auto_exit_checkbox.setChecked(config_manager.get("auto_exit", False))
            self.auto_screen_checkbox.setChecked(config_manager.get("auto_screen", False))
            try:
                from utils.ai_qr_scanner import ai_qr_scanner
                ai_qr_scanner.use_thread_pool = config_manager.get("thread_pool_enabled", False)
            except Exception:
                pass
        except Exception as e:
            print(f"[Config] Failed to load saved config: {e}")

    # ==================================================================
    # #4 — 启动时自动扫描
    # ==================================================================

    def _auto_start_if_configured(self):
        """如果配置了 auto_screen + 有默认账号，启动时自动开始屏幕扫描"""
        if not config_manager.get("auto_screen", False):
            return
        default_uid = config_manager.get("default_account", "")
        if not default_uid:
            return
        idx = account_manager.find_index_by_uid(default_uid)
        if idx is None:
            return
        self._activate_account(idx)
        self.account_table.selectRow(idx)
        self.add_log("✓ 启动自动扫描（使用默认账号）")
        # 延迟启动，等 UI 完全初始化
        QTimer.singleShot(500, self.on_start_scan)

    # ==================================================================
    # Scan Actions
    # ==================================================================

    def on_start_scan(self):
        """开始屏幕扫码"""
        if self.selected_account_index == -1:
            QMessageBox.warning(self, "提示", "请先选择一个账号！")
            return

        token = account_manager.get_account_token(self.selected_account_index)
        if not token:
            QMessageBox.warning(self, "提示", "账号Token为空，请重新添加账号！")
            return

        kuro_api.set_token(token)
        kuro_api.warm_up_connection()

        if not self.scan_window:
            self.scan_window = ScanWindow()
            self.scan_window.qr_detected.connect(self.on_qr_detected)

        self.scan_window.show()
        self.scan_window.start_scanning()

        self.start_scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.status_label.setText("状态: 屏幕扫描中...")
        self.add_log("开始屏幕扫描...")

    def on_stop_scan(self):
        """停止屏幕扫码"""
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_label.setText("状态: 待机中")
        self.add_log("已停止扫描")

    # ------------------------------------------------------------------
    # 直播流扫描
    # ------------------------------------------------------------------

    def extract_room_id(self, text: str, platform: str) -> str:
        """从输入文本中提取房间ID"""
        import re
        if text.isdigit() and len(text) >= 4:
            return text
        if platform == "douyin":
            m = re.search(r'room_id=(\d+)', text)
            if m:
                return m.group(1)
            m = re.search(r'live\.douyin\.com/(\d+)', text)
            if m:
                return m.group(1)
        elif platform == "bilibili":
            m = re.search(r'live\.bilibili\.com/(\d+)', text)
            if m:
                return m.group(1)
        m = re.search(r'\d{4,}', text)
        return m.group(0) if m else ""

    def on_start_live_scan(self):
        """开始直播流扫描"""
        if self.selected_account_index == -1:
            QMessageBox.warning(self, "提示", "请先选择一个账号！")
            return

        platform_idx = self.live_platform_combo.currentIndex()
        platform = "douyin" if platform_idx == 0 else "bilibili"

        input_text = self.live_room_input.text().strip()
        if not input_text:
            QMessageBox.warning(self, "警告", "请输入直播间ID或分享链接！")
            return

        room_id = self.extract_room_id(input_text, platform)
        if not room_id:
            QMessageBox.warning(self, "警告", "无法识别的房间ID格式！")
            return

        self.add_log(f"✓ 提取到房间ID: {room_id} (平台: {platform})")

        # 停止正在进行的扫描
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        if self.live_scanner and self.live_scanner.isRunning():
            self.live_scanner.stop()
            self.live_scanner.wait()

        # 设置 token
        token = account_manager.get_account_token(self.selected_account_index)
        kuro_api.set_token(token)

        try:
            from utils.live_stream_scanner import get_live_stream_scanner
            self.live_scanner = get_live_stream_scanner()
            self.live_scanner.qr_detected.connect(self.on_qr_detected)
            self.live_scanner.status_changed.connect(self.add_log)
            self.live_scanner.error_occurred.connect(lambda msg: self.add_log(f"❌ {msg}"))
            self.live_scanner.set_stream_url(room_id, platform)
            self.live_scanner.start()

            platform_name = "抖音" if platform == "douyin" else "B站"
            self.add_log(f"开始扫描{platform_name}直播间: {room_id}")
            self.status_label.setText(f"状态: {platform_name}直播流扫描中...")

            self.start_scan_btn.setEnabled(False)
            self.start_live_btn.setText("停止直播扫描")
            self.start_live_btn.clicked.disconnect()
            self.start_live_btn.clicked.connect(self.on_stop_live_scan)
        except Exception as e:
            self.add_log(f"❌ 启动直播流扫描失败: {e}")

    def on_stop_live_scan(self):
        """停止直播流扫描"""
        if self.live_scanner:
            self.live_scanner.stop()
            self.add_log("✓ 已停止直播流扫描")
        self.status_label.setText("状态: 待机中")
        self.start_scan_btn.setEnabled(True)
        self.start_live_btn.setText("扫描直播")
        self.start_live_btn.clicked.disconnect()
        self.start_live_btn.clicked.connect(self.on_start_live_scan)

    # ==================================================================
    # QR Detection → Login
    # ==================================================================

    def on_qr_detected(self, qr_code):
        """检测到二维码"""
        ticket = extract_kuro_ticket(qr_code) or qr_code
        if self.login_in_progress:
            if ticket == self.pending_ticket:
                self.add_log("忽略重复二维码：当前登录请求仍在处理")
            else:
                self.add_log("忽略新的二维码：当前登录请求仍在处理")
            return

        self.add_log("✓ 检测到二维码，正在登录...")
        self.pending_qr_code = qr_code
        self.pending_ticket = ticket
        self.login_in_progress = True

        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None

        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_label.setText("状态: 登录中...")

        # ---- #6 登录确认对话框 ----
        if not config_manager.get("auto_login", False):
            name = account_manager.get_account_name(self.selected_account_index) if self.selected_account_index >= 0 else "未知"
            reply = QMessageBox.question(
                self, "登录确认",
                f"正在使用账号 {name}\n登录鸣潮\n\n确认登录？",
                QMessageBox.Yes | QMessageBox.No,
            )
            if reply != QMessageBox.Yes:
                self.add_log("用户取消登录")
                self.status_label.setText("状态: 已取消")
                self.login_in_progress = False
                self.pending_ticket = ""
                return

        self.scan_thread = ScanThread(qr_code, skip_role_check=False)
        self.scan_thread.scan_result.connect(self.on_scan_result)
        self.scan_thread.log_message.connect(self.add_log)
        self.scan_thread.start()

    def on_scan_result(self, result):
        """扫码结果回调"""
        if result.get("success"):
            self.login_in_progress = False
            self.pending_ticket = ""
            self.add_log("扫码成功！")
            self.status_label.setText("状态: 登录成功")

            # #8 窗口前置
            self._bring_to_front()

            QMessageBox.information(self, "成功", "扫码登录成功！")

            # 停止所有扫描
            self._stop_all_scanners()

            # #3 自动退出
            if config_manager.get("auto_exit", False):
                self.add_log("自动退出已启用，3秒后退出...")
                QTimer.singleShot(3000, lambda: sys.exit(0))

        elif result.get("need_sms"):
            # ---- #5 短信验证专用对话框 ----
            self.add_log("⚠ 需要短信验证码")
            self._bring_to_front()

            mobile = ""
            if self.selected_account_index >= 0:
                mobile = account_manager.get_account_mobile(self.selected_account_index)

            token_for_sms = ""
            if self.selected_account_index >= 0:
                token_for_sms = account_manager.get_account_token(self.selected_account_index)

            sms_dlg = SmsDialog(token_for_sms, mobile, self)
            if sms_dlg.exec() == SmsDialog.Rejected:
                self.add_log("用户取消验证")
                self.status_label.setText("状态: 已取消")
                self.login_in_progress = False
                self.pending_ticket = ""
                return

            sms_code = sms_dlg.get_sms_code()
            auto_login = sms_dlg.get_auto_login()
            self.add_log(f"收到验证码，重新扫码...")

            self.scan_thread = ScanThread(self.pending_qr_code, skip_role_check=True)
            self.scan_thread.verify_code = sms_code
            self.scan_thread.auto_login = auto_login
            self.scan_thread.scan_result.connect(self.on_scan_result)
            self.scan_thread.log_message.connect(self.add_log)
            self.scan_thread.start()
        else:
            self.login_in_progress = False
            self.pending_ticket = ""
            message = result.get("message", "未知错误")
            self.add_log(f"❌ 扫码失败: {message}")

            # 自动重试
            if "二维码已过期" in message or "二维码已失效" in message:
                if config_manager.get("auto_retry", True) and self.scan_window and not self.scan_window.isHidden():
                    self.add_log("二维码已过期，3秒后自动重试...")
                    if hasattr(self.scan_window, "last_ticket"):
                        self.scan_window.last_ticket = ""
                    QTimer.singleShot(3000, self.auto_retry_scan)
                    return

            if "Token已过期" in message:
                self._bring_to_front()
                QMessageBox.warning(self, "提示", "登录已过期，请重新添加账号！")

            if self.scan_window:
                self.scan_window.reset_processing()

    def auto_retry_scan(self):
        if self.scan_window and not self.scan_window.isHidden():
            self.add_log("自动重试中...")
        else:
            self.add_log("扫描窗口已关闭，取消自动重试")

    # ==================================================================
    # Helpers
    # ==================================================================

    def _stop_all_scanners(self):
        """停止所有扫描器"""
        self.login_in_progress = False
        self.pending_ticket = ""
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        if self.live_scanner and self.live_scanner.isRunning():
            self.live_scanner.stop()
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.start_live_btn.setText("扫描直播")
        try:
            self.start_live_btn.clicked.disconnect()
        except RuntimeError:
            pass
        self.start_live_btn.clicked.connect(self.on_start_live_scan)

    def _bring_to_front(self):
        """#8 窗口前置提醒"""
        self.setWindowState(self.windowState() & ~Qt.WindowMinimized)
        self.raise_()
        self.activateWindow()
        # 平台特定：Windows 使用 Win32 API 强制前置
        if platform.system() == "Windows":
            try:
                import ctypes
                hwnd = int(self.winId())
                ctypes.windll.user32.ShowWindow(hwnd, 9)  # SW_RESTORE
                ctypes.windll.user32.SetForegroundWindow(hwnd)
            except Exception:
                pass

    def add_log(self, message):
        from datetime import datetime
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def show_performance_stats(self):
        if not PERF_MONITOR_AVAILABLE:
            QMessageBox.information(self, "性能统计", "性能监控系统未可用")
            return
        stats_summary = perf_monitor.get_statistics_summary()
        method_distribution = perf_monitor.get_method_distribution()
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
            extra_info.append(f"ROI预测: {roi_stats['accuracy']}% 准确率")
        except Exception:
            pass
        full_info = stats_summary + "\n\n" + method_distribution
        if extra_info:
            full_info += "\n\n" + "\n".join(extra_info)
        self.add_log("\n" + stats_summary)
        QMessageBox.information(self, "性能统计", full_info)

    # ==================================================================
    # Close
    # ==================================================================

    def closeEvent(self, event):
        self._stop_all_scanners()
        event.accept()
