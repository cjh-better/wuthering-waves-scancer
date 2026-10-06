# -*- coding: utf-8 -*-
"""主窗口 — 竞品级功能（参考 KuRo_Scanner）"""
import os
import sys
import platform
from datetime import datetime
from PySide6.QtCore import Qt, QTimer, Signal, QThread
from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QTextEdit, QMessageBox, QLineEdit,
    QCheckBox, QTableWidget, QTableWidgetItem, QHeaderView,
    QComboBox, QMenu, QAbstractItemView,
)
from PySide6.QtGui import QFont, QIcon, QAction
# 启动速度：对话框延迟导入（用到时才加载，省 ~200ms）
# _DIALOG_REGISTRY：模块级注册表，测试可用 monkeypatch.setattr 替换，
# 比 sys.modules 猜模块名稳（打包后模块路径可能变）。
_DIALOG_REGISTRY: dict = {}

def _get_dialog_class(name: str):
    """获取对话框类：优先注册表（可被测试 mock），缺失时 lazy import 并缓存。"""
    cls = _DIALOG_REGISTRY.get(name)
    if cls is not None:
        return cls
    if name == "LoginDialog":
        from ui.login_dialog import LoginDialog as _LD
        _DIALOG_REGISTRY[name] = _LD
        return _LD
    elif name == "ScanWindow":
        from ui.scan_window import ScanWindow as _SW
        _DIALOG_REGISTRY[name] = _SW
        return _SW
    elif name == "SmsDialog":
        from ui.sms_dialog import SmsDialog as _SD
        _DIALOG_REGISTRY[name] = _SD
        return _SD
    raise ImportError(f"Unknown dialog: {name}")
from utils.config_manager import config_manager
from utils.account_manager import account_manager
from utils.kuro_api import KuroAPI, kuro_api
from utils.qr_payload import extract_kuro_ticket
from utils.log import get_logger


logger = get_logger("MainWindow")

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
        # 快照请求头：run() 在工作线程执行，若直接读 kuro_api.headers，
        # 会与 UI 线程的 set_token()（切账号）竞态，导致这次扫码带错 token。
        # 构造发生在 UI 线程，快照是扫码开始时的正确 token；连接复用不受影响。
        self._headers = dict(kuro_api.headers)

    def run(self):
        """执行扫码"""
        try:
            if not self.skip_role_check:
                role_result = kuro_api.get_role_infos(self.qr_code, headers=self._headers)
                if PERF_MONITOR_AVAILABLE and perf_monitor.current_scan:
                    perf_monitor.mark_api_roleinfo_done()
                if is_token_expired_code(role_result.get("code")):
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
                headers=self._headers,
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
            elif is_token_expired_code(scan_result.get("code")):
                # token 过期（skip_role_check 开启时 roleInfos 检查被跳过，
                # 这里必须兜底，否则过期会掉进通用失败分支）
                self.log_message.emit("❌ Token已过期")
                self.scan_result.emit({"success": False, "message": "Token已过期"})
                if PERF_MONITOR_AVAILABLE:
                    perf_monitor.end_scan(success=False)
            elif scan_result.get("code") == 2240:
                self.log_message.emit("⚠ 需要短信验证码")
                self.scan_result.emit({"success": False, "message": "需要短信验证码", "need_sms": True})
            else:
                if self.verify_code:
                    scan_result_retry = kuro_api.scan_login(self.qr_code, "", headers=self._headers)
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

from utils.token_status import classify_token_check_response, is_token_expired_code


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
            status, message = classify_token_check_response(resp)
            self.result.emit(self.row, status, message)
        except Exception as e:
            self.result.emit(self.row, "未知", f"检查账号状态失败: {e}")


class ShortLinkResolveThread(QThread):
    """后台解析分享短链（v.douyin.com / b23.tv）。

    跳转解析是同步网络请求（最多约 8 秒），放 UI 线程会假死，
    因此用工作线程做完再 signal 回 UI 线程继续。
    """

    result = Signal(str, str)  # (room_id, platform)

    def __init__(self, short_url: str, platform: str, parent=None):
        super().__init__(parent)
        self.short_url = short_url
        self.platform = platform

    def run(self):
        try:
            from utils import room_url
            room_id = room_url.resolve_room_id(self.short_url, self.platform)
        except Exception:
            room_id = ""
        self.result.emit(room_id or "", self.platform)


# ======================================================================
# MainWindow
# ======================================================================

class MainWindow(QMainWindow):
    """主窗口"""

    def __init__(self):
        super().__init__()
        self.setWindowTitle("鸣潮抢码器 v3.0 - Release")
        # 窗口可自由调整：默认横向长方形，最小尺寸保底
        self.resize(1120, 760)
        self.setMinimumSize(880, 620)
        # 优化65：恢复上次窗口位置
        try:
            from utils.config_manager import config_manager as _cm_geo
            pos = _cm_geo.get("window_pos", None)
            if isinstance(pos, (list, tuple)) and len(pos) == 2:
                self.move(int(pos[0]), int(pos[1]))
        except Exception:
            pass

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
        # 登录状态锁：fast-path 回调在解码线程调用，需线程安全
        import threading as _th
        self._login_lock = _th.Lock()
        self._fast_login_started = False
        self._sched_timer = None
        self._sched_last_trigger = ""
        self.account_check_threads = []
        self.short_link_thread = None  # 分享短链后台解析线程
        self.selected_account_index = -1  # 当前选中的账号行

        self.setup_ui()
        self.apply_styles()
        # 样式影响 sizeHint（如 checkbox min-height），需强制重新布局
        try:
            self.style().polish(self)
            for card_attr in ("info_widget", "control_widget", "log_widget"):
                card = getattr(self, card_attr, None)
                if card and card.layout():
                    card.layout().invalidate()
                    card.layout().activate()
        except Exception:
            pass
        self._load_accounts_to_table()
        self._load_saved_config()
        self._auto_start_if_configured()
        # 定时抢码：启动时若已启用，启动检查器
        if config_manager.get("scheduled_grab_enabled", False):
            self._ensure_sched_timer()
        # 崩溃自动恢复：上次崩溃且有监控状态，自动重启
        self._check_crash_recovery()

    # ==================================================================
    # UI Setup
    # ==================================================================

    def setup_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout(central_widget)
        main_layout.setSpacing(14)
        main_layout.setContentsMargins(20, 20, 20, 20)

        # 标题栏：左标题 + 右主题切换按钮
        title_bar = QHBoxLayout()
        title_bar.setContentsMargins(4, 4, 4, 8)

        title_wrap = QVBoxLayout()
        title_wrap.setSpacing(2)
        title = QLabel("鸣潮抢码器")
        title.setObjectName("appTitle")
        title.setAlignment(Qt.AlignCenter)
        subtitle = QLabel("WUTHERING WAVES  •  QR SNIPER")
        subtitle.setObjectName("appSubtitle")
        subtitle.setAlignment(Qt.AlignCenter)
        title_wrap.addWidget(title)
        title_wrap.addWidget(subtitle)

        title_bar.addStretch(1)
        title_bar.addLayout(title_wrap)
        title_bar.addStretch(1)

        # 主题切换按钮（右上角）
        self.theme_btn = QPushButton()
        self.theme_btn.setObjectName("themeBtn")
        self.theme_btn.setCursor(Qt.PointingHandCursor)
        self.theme_btn.setToolTip("切换浅色 / 深色主题")
        self.theme_btn.clicked.connect(self.on_toggle_theme)
        title_bar.addWidget(self.theme_btn, alignment=Qt.AlignTop)

        main_layout.addLayout(title_bar)

        self._setup_account_section(main_layout)
        self._setup_control_section(main_layout)
        self._setup_log_section(main_layout)

        # 入场动效：三卡片 stagger 纯透明度淡入（不碰几何，与布局无冲突）
        QTimer.singleShot(60, self._play_entrance_animations)

    def _play_entrance_animations(self) -> None:
        """播放三卡片的 stagger 入场动画。"""
        try:
            cards = []
            for attr in ("info_widget", "control_widget", "log_widget"):
                w = getattr(self, attr, None)
                if w is not None:
                    cards.append(w)
            for i, card in enumerate(cards):
                self._animate_entrance(card, delay_ms=i * 90)
        except Exception:
            pass

    def _section_header(self, text: str) -> QWidget:
        """分区标题：简洁文本，左侧金色边框线（样式由主题表 QLabel#sectionTitle 提供）。"""
        label = QLabel(f"  {text}")
        label.setObjectName("sectionTitle")
        return label

    def _animate_entrance(self, widget, delay_ms: int = 0) -> None:
        """卡片入场：纯透明度淡入，350ms ease-out，stagger 延迟。

        只做 opacity（QGraphicsOpacityEffect 仅影响绘制，不碰几何），
        不动画 pos——layout 管理的 widget 动 pos 会与布局打架导致错位。
        """
        from PySide6.QtCore import QPropertyAnimation, QEasingCurve
        from PySide6.QtWidgets import QGraphicsOpacityEffect

        def _start():
            try:
                effect = QGraphicsOpacityEffect(widget)
                effect.setOpacity(0.0)
                widget.setGraphicsEffect(effect)
                fade = QPropertyAnimation(effect, b"opacity")
                fade.setDuration(380)
                fade.setStartValue(0.0)
                fade.setEndValue(1.0)
                fade.setEasingCurve(QEasingCurve.Type.OutCubic)

                def _cleanup():
                    # 动画结束移除 effect，避免影响后续样式/性能
                    try:
                        widget.setGraphicsEffect(None)
                    except Exception:
                        pass

                fade.finished.connect(_cleanup)
                fade.start()
                # 防止被 GC：挂在 widget 上
                widget._entrance_fade = fade
                widget._entrance_effect = effect
            except Exception:
                pass

        QTimer.singleShot(delay_ms, _start)

    # ------------------------------------------------------------------
    # 1. 多账号管理区域
    # ------------------------------------------------------------------

    def _setup_account_section(self, parent_layout):
        info_widget = QWidget()
        info_widget.setObjectName("infoWidget")
        self.info_widget = info_widget
        info_layout = QVBoxLayout(info_widget)
        info_layout.setSpacing(10)
        info_layout.setContentsMargins(18, 16, 18, 16)

        # 标题行 + 添加账号按钮
        header = QHBoxLayout()
        header.addWidget(self._section_header("账号管理"))
        header.addStretch()

        add_btn = QPushButton("＋ 添加账号")
        add_btn.setObjectName("loginBtn")
        add_btn.setFixedHeight(36)
        add_btn.setMinimumWidth(120)
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

        parent_layout.addWidget(info_widget, 0)

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
        idx_item.setFlags(idx_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.account_table.setItem(row, 0, idx_item)

        # UID列（只读）
        uid_item = QTableWidgetItem(uid)
        uid_item.setFlags(uid_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.account_table.setItem(row, 1, uid_item)

        # 昵称列（只读）
        name_item = QTableWidgetItem(name)
        name_item.setFlags(name_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
        self.account_table.setItem(row, 2, name_item)

        # 状态列（只读）
        status_item = QTableWidgetItem(status or "未知")
        status_item.setFlags(status_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
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
                item.setFlags(item.flags() & ~Qt.ItemFlag.ItemIsEditable)
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

        refresh_action = QAction("🔄 重新获取Token", self)
        refresh_action.triggered.connect(self._on_refresh_account_token)
        menu.addAction(refresh_action)

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

    def _on_refresh_account_token(self):
        """一键重新获取 Token。

        用账号保存的手机号直接打开登录对话框（已预填），短信验证通过后
        原位更新 token，无需手动删除再添加。
        """
        row = self._get_selected_row()
        if row == -1:
            QMessageBox.information(self, "提示", "没有选择任何账号")
            return
        if (self.scan_window and self.scan_window.isVisible()) or \
           (self.live_scanner and self.live_scanner.isRunning()):
            QMessageBox.information(self, "提示", "请先停止扫描！")
            return
        mobile = account_manager.get_account_mobile(row)
        if not mobile:
            QMessageBox.warning(
                self, "无法一键续期",
                "该账号未保存手机号，无法一键重新获取。\n请删除后重新添加账号。",
            )
            return
        name = account_manager.get_account_name(row) or account_manager.get_account_uid(row)
        LoginDialog = _get_dialog_class('LoginDialog')
        dialog = LoginDialog(parent=self, mobile=mobile)
        dialog.setWindowTitle(f"重新获取Token - {name}")
        dialog.login_success.connect(self._on_login_success_add_account)
        # _on_login_success_add_account 已处理"账号存在→原位更新 token"，
        # 这里只需把状态刷成可用并同步当前 token
        dialog.login_success.connect(lambda _data, r=row: self._mark_account_token_fresh(r))
        dialog.exec()

    def _mark_account_token_fresh(self, row: int):
        """Token 续期成功后：状态置为可用，并同步当前生效的 token。"""
        if row < 0 or row >= account_manager.size():
            return
        account_manager.set_account_status(row, "可用", "")
        self._update_account_status_cell(row, "可用")
        if row == self.selected_account_index:
            # 当前选中的账号：让 kuro_api 立即用上新 token
            self._activate_account(row)
        self.add_log("✓ Token 已更新，账号恢复可用")

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
        self.control_widget = control_widget
        control_layout = QVBoxLayout(control_widget)
        control_layout.setSpacing(12)
        control_layout.setContentsMargins(18, 16, 18, 16)

        control_layout.addWidget(self._section_header("扫码控制"))

        # 屏幕扫描按钮行
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)
        self.start_scan_btn = QPushButton("◉  开始扫码")
        self.start_scan_btn.setObjectName("primaryBtn")
        self.start_scan_btn.setFixedHeight(52)
        self.start_scan_btn.clicked.connect(self.on_start_scan)
        btn_layout.addWidget(self.start_scan_btn)

        self.stop_scan_btn = QPushButton("■  停止")
        self.stop_scan_btn.setObjectName("stopBtn")
        self.stop_scan_btn.setFixedHeight(52)
        self.stop_scan_btn.setEnabled(False)
        self.stop_scan_btn.clicked.connect(self.on_stop_scan)
        btn_layout.addWidget(self.stop_scan_btn)
        control_layout.addLayout(btn_layout)

        # 选项复选框（直接加入主布局，避免嵌套布局的几何问题）
        self.thread_pool_checkbox = QCheckBox("启用多线程池加速（实验性）")
        self.thread_pool_checkbox.setMinimumHeight(28)
        self.thread_pool_checkbox.setChecked(config_manager.get("thread_pool_enabled", False))
        self.thread_pool_checkbox.stateChanged.connect(self.on_thread_pool_changed)
        control_layout.addWidget(self.thread_pool_checkbox)

        self.auto_login_checkbox = QCheckBox("检测到二维码后自动登录")
        self.auto_login_checkbox.setMinimumHeight(28)
        self.auto_login_checkbox.setChecked(config_manager.get("auto_login", False))
        self.auto_login_checkbox.stateChanged.connect(self.on_auto_login_changed)
        control_layout.addWidget(self.auto_login_checkbox)

        self.auto_exit_checkbox = QCheckBox("扫码成功后自动退出")
        self.auto_exit_checkbox.setMinimumHeight(28)
        self.auto_exit_checkbox.setChecked(config_manager.get("auto_exit", False))
        self.auto_exit_checkbox.stateChanged.connect(self._on_auto_exit_changed)
        control_layout.addWidget(self.auto_exit_checkbox)

        self.auto_screen_checkbox = QCheckBox("启动时自动监视屏幕")
        self.auto_screen_checkbox.setMinimumHeight(28)
        self.auto_screen_checkbox.setChecked(config_manager.get("auto_screen", False))
        self.auto_screen_checkbox.stateChanged.connect(self._on_auto_screen_changed)
        control_layout.addWidget(self.auto_screen_checkbox)


        # 自动重试始终开启
        config_manager.set("auto_retry", True, save=False)

        # 直播流扫描区域
        # 直播行1：平台 + 房间输入 + 扫描直播（主操作）
        live_layout = QHBoxLayout()
        live_layout.setSpacing(10)

        self.live_platform_combo = QComboBox()
        self.live_platform_combo.addItems(["抖音", "B站"])
        self.live_platform_combo.setFixedHeight(44)
        self.live_platform_combo.setFixedWidth(90)
        live_layout.addWidget(self.live_platform_combo)

        self.live_room_input = QLineEdit()
        self.live_room_input.setPlaceholderText("直播间ID / 分享链接 / 短链")
        self.live_room_input.setFixedHeight(44)
        # 优化69：失焦自动 trim，避免前后空格导致解析失败
        self.live_room_input.editingFinished.connect(
            lambda: self.live_room_input.setText(self.live_room_input.text().strip())
        )
        live_layout.addWidget(self.live_room_input, 1)

        self.start_live_btn = QPushButton("▶ 扫描直播")
        self.start_live_btn.setObjectName("primaryBtn")
        self.start_live_btn.setFixedHeight(44)
        self.start_live_btn.clicked.connect(self.on_start_live_scan)
        live_layout.addWidget(self.start_live_btn)
        control_layout.addLayout(live_layout)

        # 直播行2：辅助功能（幽灵按钮，次要层级）
        live_tools_layout = QHBoxLayout()
        live_tools_layout.setSpacing(8)

        self.room_monitor_btn = QPushButton("开播监控")
        self.room_monitor_btn.setObjectName("ghostBtn")
        self.room_monitor_btn.setFixedHeight(36)
        self.room_monitor_btn.clicked.connect(self.on_open_room_monitor)
        live_tools_layout.addWidget(self.room_monitor_btn)

        self.grab_stats_btn = QPushButton("抢码战绩")
        self.grab_stats_btn.setObjectName("ghostBtn")
        self.grab_stats_btn.setFixedHeight(36)
        self.grab_stats_btn.clicked.connect(self.on_open_grab_stats)
        live_tools_layout.addWidget(self.grab_stats_btn)

        self.float_btn = QPushButton("悬浮窗")
        self.float_btn.setObjectName("ghostBtn")
        self.float_btn.setFixedHeight(36)
        self.float_btn.clicked.connect(self.on_toggle_floating)
        live_tools_layout.addWidget(self.float_btn)

        live_tools_layout.addStretch()

        # 定时抢码：到点自动开始直播扫描
        self.sched_grab_check = QCheckBox("定时")
        self.sched_grab_check.setMinimumHeight(28)
        self.sched_grab_check.setChecked(bool(config_manager.get("scheduled_grab_enabled", False)))
        self.sched_grab_check.toggled.connect(self._on_sched_grab_toggled)
        live_tools_layout.addWidget(self.sched_grab_check)

        self.sched_grab_time = QLineEdit()
        self.sched_grab_time.setPlaceholderText("HH:MM")
        self.sched_grab_time.setText(str(config_manager.get("scheduled_grab_time", "")))
        self.sched_grab_time.setFixedWidth(76)
        self.sched_grab_time.setFixedHeight(36)
        self.sched_grab_time.editingFinished.connect(self._on_sched_time_changed)
        live_tools_layout.addWidget(self.sched_grab_time)
        control_layout.addLayout(live_tools_layout)

        # 速度模式预设
        preset_layout = QHBoxLayout()
        preset_layout.setSpacing(10)
        preset_label = QLabel("速度模式")
        preset_label.setObjectName("presetLabel")
        preset_layout.addWidget(preset_label)
        from utils.speed_presets import PRESETS, PRESET_ORDER, current_preset, apply_preset
        self.preset_combo = QComboBox()
        for name in PRESET_ORDER:
            self.preset_combo.addItem(PRESETS[name]["label"], name)
        self.preset_combo.setCurrentIndex(PRESET_ORDER.index(current_preset()))
        self.preset_combo.setFixedHeight(36)
        self.preset_combo.setMinimumWidth(140)
        self.preset_combo.setToolTip(
            "\n".join(f"{PRESETS[n]['label']}: {PRESETS[n]['desc']}" for n in PRESET_ORDER)
        )
        self.preset_combo.currentIndexChanged.connect(self.on_preset_changed)
        preset_layout.addWidget(self.preset_combo)
        preset_layout.addStretch()
        control_layout.addLayout(preset_layout)

        # 状态胶囊（带呼吸灯）
        from ui.status_pill import StatusPill
        self.status_pill = StatusPill()
        control_layout.addWidget(self.status_pill)
        # 兼容旧代码：status_label 指向胶囊的 label
        self.status_label = self.status_pill._label

        parent_layout.addWidget(control_widget, 0)

    # ------------------------------------------------------------------
    # 3. 日志区域
    # ------------------------------------------------------------------

    def _setup_log_section(self, parent_layout):
        log_widget = QWidget()
        log_widget.setObjectName("logWidget")
        self.log_widget = log_widget
        log_layout = QVBoxLayout(log_widget)
        log_layout.setSpacing(10)
        log_layout.setContentsMargins(18, 16, 18, 16)

        self.log_text = QTextEdit()
        self.log_text.setObjectName("logText")
        self.log_text.setReadOnly(True)
        self.log_text.setMinimumHeight(180)

        header = QHBoxLayout()
        header.addWidget(self._section_header("运行日志"))
        header.addStretch()
        clear_log_btn = QPushButton("清空")
        clear_log_btn.setObjectName("ghostBtn")
        clear_log_btn.setFixedHeight(32)
        clear_log_btn.setFixedWidth(80)
        clear_log_btn.clicked.connect(self.log_text.clear)
        header.addWidget(clear_log_btn)
        log_layout.addLayout(header)

        log_layout.addWidget(self.log_text)

        log_btn_layout = QHBoxLayout()
        log_btn_layout.setSpacing(8)

        if PERF_MONITOR_AVAILABLE:
            perf_btn = QPushButton("性能统计")
            perf_btn.setObjectName("ghostBtn")
            perf_btn.setFixedHeight(34)
            perf_btn.clicked.connect(self.show_performance_stats)
            log_btn_layout.addWidget(perf_btn)

        log_layout.addLayout(log_btn_layout)
        log_layout.addWidget(self.log_text)
        parent_layout.addWidget(log_widget, 1)

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
        self.add_log("✓ 智能ROI区域预测")
        self.add_log("✓ 智能阶梯式重试 + 组件预热")
        self.add_log("━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")

        # AI模型状态（模型懒加载：延迟展示，等后台预热完成）
        QTimer.singleShot(4000, self._log_ai_status)

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
            else:
                # 模型缺失/加载失败：明确告诉用户已降级，避免"闪退/识别差"时无头绪
                self.add_log("⚠️ AI 模型未加载，已降级为传统识别模式（识别率可能下降）")
                self.add_log("⚠️ 请确认 ScanModel 目录完整（4 个模型文件都在）")
        except Exception:
            pass
        self.add_log("请先添加账号，选中后点击【开始扫码】")

    # ==================================================================
    # Styles
    # ==================================================================

    def apply_styles(self):
        """应用当前主题样式表（从配置读取主题，默认深色）。"""
        from ui.theme import get_stylesheet, THEME_DARK
        theme = config_manager.get("theme", THEME_DARK)
        self._current_theme = theme
        self.setStyleSheet(get_stylesheet(theme))
        self._refresh_theme_btn()

    def _refresh_theme_btn(self):
        """刷新主题切换按钮的文字（🌙 深色 / ☀️ 浅色）。"""
        from ui.theme import THEME_LIGHT
        if not hasattr(self, "theme_btn"):
            return
        if getattr(self, "_current_theme", "dark") == THEME_LIGHT:
            self.theme_btn.setText("🌙 深色")
        else:
            self.theme_btn.setText("☀️ 浅色")

    def on_toggle_theme(self):
        """切换浅色 / 深色主题，立即生效并保存偏好。"""
        from ui.theme import get_stylesheet, THEME_DARK, THEME_LIGHT
        cur = getattr(self, "_current_theme", THEME_DARK)
        new_theme = THEME_LIGHT if cur == THEME_DARK else THEME_DARK
        self._current_theme = new_theme
        config_manager.set("theme", new_theme)
        self.setStyleSheet(get_stylesheet(new_theme))
        self._refresh_theme_btn()
        self.add_log(f"已切换为{'浅色' if new_theme == THEME_LIGHT else '深色'}主题")

    # ==================================================================
    # Account Actions
    # ==================================================================

    def on_add_account(self):
        """添加账号（打开登录对话框）"""
        if (self.scan_window and self.scan_window.isVisible()) or \
           (self.live_scanner and self.live_scanner.isRunning()):
            QMessageBox.information(self, "提示", "请先停止扫描！")
            return
        LoginDialog = _get_dialog_class('LoginDialog')
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
            logger.warning(f"[Config] Failed to load saved config: {e}")

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
            ScanWindow = _get_dialog_class('ScanWindow')
            self.scan_window = ScanWindow()
            self.scan_window.qr_detected.connect(self.on_qr_detected)

        self.scan_window.show()
        self.scan_window.start_scanning()

        self.start_scan_btn.setEnabled(False)
        self.stop_scan_btn.setEnabled(True)
        self.status_pill.set_status("屏幕扫描中", "active")
        self.add_log("开始屏幕扫描...")

    def on_stop_scan(self):
        """停止屏幕扫码"""
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_pill.set_status("待机中", "idle")
        self.add_log("已停止扫描")

    # ------------------------------------------------------------------
    # 直播流扫描
    # ------------------------------------------------------------------

    def extract_room_id(self, text: str, platform: str) -> str:
        """从输入文本中提取房间ID（纯本地解析，不做网络请求）。

        短链（如 v.douyin.com/xxxx）无法直接提取时返回 ""，
        调用方（on_start_live_scan）会走跳转解析。
        """
        from utils import room_url
        return room_url.extract_room_id(text, platform)

    def on_open_room_monitor(self):
        """打开开播监控对话框。"""
        from ui.room_monitor_dialog import RoomMonitorDialog
        dlg = RoomMonitorDialog(self)
        dlg.exec()

    def _on_sched_grab_toggled(self, checked: bool) -> None:
        """定时抢码开关。"""
        config_manager.set("scheduled_grab_enabled", bool(checked))
        if checked:
            t = self.sched_grab_time.text().strip()
            if not t:
                self.add_log("请先设置定时时间（HH:MM）")
                self.sched_grab_check.setChecked(False)
                config_manager.set("scheduled_grab_enabled", False)
                return
            self.add_log(f"定时抢码已启用：{t} 自动开始")
            self._ensure_sched_timer()
        else:
            self.add_log("定时抢码已关闭")

    def _on_sched_time_changed(self) -> None:
        """定时时间修改。"""
        t = self.sched_grab_time.text().strip()
        # 简单校验 HH:MM
        import re
        if t and not re.match(r"^([01]?\d|2[0-3]):[0-5]\d$", t):
            self.add_log("时间格式错误，应为 HH:MM（如 20:00）")
            return
        config_manager.set("scheduled_grab_time", t)
        if t and self.sched_grab_check.isChecked():
            self._ensure_sched_timer()

    def _ensure_sched_timer(self) -> None:
        """确保定时检查器在运行（30秒检查一次）。"""
        if getattr(self, "_sched_timer", None) is None:
            self._sched_timer = QTimer(self)
            self._sched_timer.timeout.connect(self._check_scheduled_grab)
            self._sched_timer.start(30_000)
            # 立即检查一次（防止刚好错过）
            self._check_scheduled_grab()

    def _check_scheduled_grab(self) -> None:
        """检查是否到定时时间，到则自动开始直播扫描。"""
        if not config_manager.get("scheduled_grab_enabled", False):
            return
        t_str = str(config_manager.get("scheduled_grab_time", "")).strip()
        if not t_str:
            return
        try:
            now = datetime.now().strftime("%H:%M")
            if now != t_str:
                return
            # 到点！避免重复触发（同一分钟内只触发一次）
            last = getattr(self, "_sched_last_trigger", "")
            if last == t_str + datetime.now().strftime("%Y-%m-%d"):
                return
            self._sched_last_trigger = t_str + datetime.now().strftime("%Y-%m-%d")
            self.add_log(f"⏰ 定时时间到（{t_str}），自动开始直播扫描")
            # 如果已在扫描，跳过
            if self.live_scanner and self.live_scanner.is_running:
                self.add_log("直播扫描已在运行，跳过定时触发")
                return
            # M5修复：定时抢码是无人值守场景，on_start_live_scan 内的
            # QMessageBox 会阻塞事件循环导致对话框堆积；先校验，不满足
            # 只记日志不弹窗
            if self.selected_account_index == -1:
                self.add_log("⏰ 定时触发跳过：未选择账号")
                return
            if not self.live_room_input.text().strip():
                self.add_log("⏰ 定时触发跳过：未输入直播间")
                return
            self.on_start_live_scan()
        except Exception as e:
            self.add_log(f"定时触发失败: {e}")

    def _check_crash_recovery(self) -> None:
        """崩溃自动恢复：上次崩溃退出且有监控状态，自动重启监控。"""
        try:
            from utils.crash_recovery import was_crash, load_monitor_state
            if not was_crash():
                return
            state = load_monitor_state()
            if not state:
                return
            room_id = state.get("room_id", "")
            platform = state.get("platform", "bilibili")
            if not room_id:
                return
            self.add_log(f"⚠️ 检测到上次崩溃退出，自动恢复监控: {room_id} ({platform})")
            # 延迟 3 秒启动，等 UI 完全就绪
            QTimer.singleShot(3000, lambda: self._start_live_scan_with_room_id(room_id, platform))
        except Exception as e:
            self.add_log(f"崩溃恢复失败: {e}")

    def on_toggle_floating(self) -> None:
        """切换悬浮状态窗显示/隐藏。"""
        if getattr(self, "_floating_win", None) is None:
            from ui.floating_status import FloatingStatusWindow
            self._floating_win = FloatingStatusWindow()
            self._floating_win.set_status_provider(self._get_floating_status)
            # 默认放在右上角（QApplication 已在模块顶层导入）
            screen = QApplication.primaryScreen().availableGeometry()
            self._floating_win.move(screen.width() - 240, 40)
        if self._floating_win.isVisible():
            self._floating_win.hide()
        else:
            self._floating_win.show()

    def _get_floating_status(self) -> dict:
        """悬浮窗状态数据源。"""
        status = "未启动"
        room = "-"
        if self.live_scanner and self.live_scanner.is_running:
            status = "监控中"
            room = getattr(self.live_scanner, "stream_url", "-")[:20]
        elif self.scan_window and self.scan_window.isVisible():
            status = "屏幕扫码中"
        detected = success = 0
        try:
            from utils.grab_stats import grab_stats
            stats = grab_stats.get_today_stats()
            detected = stats.get("detected", 0)
            success = stats.get("success", 0)
        except Exception:
            pass
        return {"status": status, "room": room, "detected": detected, "success": success}

    def on_open_grab_stats(self):
        """打开抢码战绩对话框。"""
        from ui.grab_stats_dialog import GrabStatsDialog
        dlg = GrabStatsDialog(self)
        dlg.exec()

    def on_preset_changed(self, index):
        """速度模式切换：应用预设（立即生效于下次扫描/登录）。"""
        from utils.speed_presets import PRESETS, apply_preset
        name = self.preset_combo.itemData(index)
        if apply_preset(name):
            self.add_log(f"速度模式已切换为：{PRESETS[name]['label']}")

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
            # 可能是分享短链（v.douyin.com / b23.tv）：后台跟随跳转解析，
            # 不能放 UI 线程（最多约 8 秒假死）
            from utils import room_url
            short_url = room_url.find_short_link(input_text)
            if short_url:
                self._resolve_short_link_async(short_url, platform)
                return
        if not room_id:
            QMessageBox.warning(
                self, "警告",
                "无法识别房间号！\n请粘贴直播间分享链接或纯数字房间号。",
            )
            return

        self._start_live_scan_with_room_id(room_id, platform)

    def _resolve_short_link_async(self, short_url: str, platform: str):
        """后台解析短链，完成后回到 UI 线程继续开播。"""
        # 防止重复点击：上一次还没解析完
        if self.short_link_thread and self.short_link_thread.isRunning():
            return
        self.add_log("检测到分享短链，后台解析中...")
        self.status_pill.set_status("解析分享链接中", "working")
        self.start_live_btn.setEnabled(False)
        self.short_link_thread = ShortLinkResolveThread(short_url, platform, self)
        self.short_link_thread.result.connect(self._on_short_link_resolved)
        self.short_link_thread.finished.connect(self._on_short_link_thread_finished)
        self.short_link_thread.start()

    def _on_short_link_thread_finished(self):
        self.short_link_thread = None

    def _on_short_link_resolved(self, room_id: str, platform: str):
        """短链解析完成（UI 线程）：继续开播或报错。"""
        self.start_live_btn.setEnabled(True)
        if not room_id:
            self.status_pill.set_status("待机中", "idle")
            QMessageBox.warning(
                self, "警告",
                "无法识别房间号！\n请粘贴直播间分享链接或纯数字房间号。",
            )
            return
        self.add_log(f"✓ 短链解析出房间ID: {room_id}")
        self._start_live_scan_with_room_id(room_id, platform)

    def _start_live_scan_with_room_id(self, room_id: str, platform: str):
        self.add_log(f"✓ 提取到房间ID: {room_id} (平台: {platform})")
        # 崩溃恢复：保存监控状态
        try:
            from utils.crash_recovery import save_monitor_state
            save_monitor_state(room_id, platform)
        except Exception:
            pass

        # 停止正在进行的扫描
        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None
        if self.live_scanner and self.live_scanner.isRunning():
            self.live_scanner.stop()
            # 有界等待：若底层网络 read 不响应 release，无限 wait 会永久冻住 UI
            if not self.live_scanner.wait(5000):
                # M2修复：超时说明旧线程仍在运行，此时调 start() 是 no-op，
                # 会导致"UI显示新房间、实际监控旧房间"的静默错误；直接报错返回
                self.add_log("❌ 旧直播线程停止超时，请稍后重试")
                return

        # 设置 token
        token = account_manager.get_account_token(self.selected_account_index)
        kuro_api.set_token(token)

        try:
            from utils.live_stream_scanner import get_live_stream_scanner
            self.live_scanner = get_live_stream_scanner()
            self.live_scanner.qr_detected.connect(
                self.on_qr_detected, Qt.ConnectionType.UniqueConnection
            )
            # 零延迟提交：auto_login 时解码线程直接启动登录（线程安全）
            self.live_scanner.set_qr_fast_callback(self._on_qr_fast)
            self.live_scanner.status_changed.connect(
                self.add_log, Qt.ConnectionType.UniqueConnection
            )
            # NOTE: a named slot (not a lambda) is required for
            # Qt.UniqueConnection to de-duplicate repeated starts, because
            # the scanner is a process-wide singleton.
            self.live_scanner.error_occurred.connect(
                self.on_live_scan_error, Qt.ConnectionType.UniqueConnection
            )
            self.live_scanner.set_stream_url(room_id, platform)
            self.live_scanner.start()

            platform_name = "抖音" if platform == "douyin" else "B站"
            self.add_log(f"开始扫描{platform_name}直播间: {room_id}")
            self.status_pill.set_status(f"{platform_name}直播监控中", "active")

            self.start_scan_btn.setEnabled(False)
            self.start_live_btn.setText("停止直播扫描")
            self.start_live_btn.clicked.disconnect()
            self.start_live_btn.clicked.connect(self.on_stop_live_scan)
        except Exception as e:
            self.add_log(f"❌ 启动直播流扫描失败: {e}")

    def on_live_scan_error(self, msg: str):
        """直播流错误：展示细分原因，并把 UI 复位到待机状态。

        之前错误只写日志，按钮还卡在"停止直播扫描"、状态还显示
        "扫描中"，用户只能重启应用才能重试。
        """
        self.add_log(f"❌ {msg}")
        self.status_pill.set_status("待机中", "idle")
        self.start_scan_btn.setEnabled(True)
        self.start_live_btn.setText("扫描直播")
        try:
            self.start_live_btn.clicked.disconnect()
        except (TypeError, RuntimeError):
            pass
        self.start_live_btn.clicked.connect(self.on_start_live_scan)

    def on_stop_live_scan(self):
        """停止直播流扫描"""
        if self.live_scanner:
            self.live_scanner.stop()
            self.add_log("✓ 已停止直播流扫描")
        # 清除崩溃恢复状态（用户主动停止，下次不自动恢复）
        try:
            from utils.crash_recovery import clear_monitor_state
            clear_monitor_state()
        except Exception:
            pass
        self.status_pill.set_status("待机中", "idle")
        self.start_scan_btn.setEnabled(True)
        self.start_live_btn.setText("扫描直播")
        self.start_live_btn.clicked.disconnect()
        self.start_live_btn.clicked.connect(self.on_start_live_scan)

    # ==================================================================
    # QR Detection → Login
    # ==================================================================

    def _on_qr_fast(self, qr_code: str, ticket: str) -> None:
        """零延迟登录提交（解码线程直接调用，线程安全）。

        仅在 auto_login=True 时生效：跳过 signal→UI 线程往返，直接启动
        ScanThread。UI 更新仍走 on_qr_detected（signal），但登录已在途。
        非 auto_login 时返回，由 on_qr_detected 弹确认框。
        """
        # U1优化：config_manager 已在模块顶层导入，避免热路径重复 import
        if not config_manager.get("auto_login", False):
            return
        with self._login_lock:
            if self.login_in_progress:
                return
            # 标记占用，on_qr_detected 看到后跳过重复启动
            self.login_in_progress = True
            self.pending_qr_code = qr_code
            self.pending_ticket = ticket
            self._fast_login_started = True
        # 在解码线程直接启动 ScanThread（QThread.start() 线程安全）
        skip_role = bool(_cm.get("live_skip_role_check", True))
        try:
            self.scan_thread = ScanThread(qr_code, skip_role_check=skip_role)
            self.scan_thread.scan_result.connect(self.on_scan_result)
            self.scan_thread.log_message.connect(self.add_log)
            self.scan_thread.start()
            from utils.grab_stats import grab_stats
            grab_stats.record_detected()
        except Exception:
            with self._login_lock:
                self.login_in_progress = False
                self._fast_login_started = False

    def on_qr_detected(self, qr_code):
        """检测到二维码（UI 线程，signal 触发）"""
        with self._login_lock:
            # ticket 前置：fast-path 已提取并存入 pending_ticket，直接复用，
            # 避免在 UI 线程重复解析（decode 线程已做过一次）
            if qr_code == self.pending_qr_code and self.pending_ticket:
                ticket = self.pending_ticket
            else:
                ticket = extract_kuro_ticket(qr_code) or qr_code
            fast_started = getattr(self, "_fast_login_started", False)
            if self.login_in_progress and not fast_started:
                # 非 fast-path 的重复（上次未完成），忽略
                if ticket == self.pending_ticket:
                    self.add_log("忽略重复二维码：当前登录请求仍在处理")
                else:
                    self.add_log("忽略新的二维码：当前登录请求仍在处理")
                return
            if not fast_started:
                # 非 fast-path：标记占用
                self.login_in_progress = True
                self.pending_qr_code = qr_code
                self.pending_ticket = ticket
            # fast-path 已在途：只做 UI 更新，不重复启动
        self.add_log("✓ 检测到二维码，正在登录...")
        if not fast_started:
            from utils.grab_stats import grab_stats
            grab_stats.record_detected()

        if self.scan_window:
            self.scan_window.close()
            self.scan_window = None

        self.start_scan_btn.setEnabled(True)
        self.stop_scan_btn.setEnabled(False)
        self.status_pill.set_status("登录中", "working")

        if fast_started:
            # fast-path 已启动登录，UI 更新完成即可
            # 重置标志（下次 QR 重新走 fast-path）
            with self._login_lock:
                self._fast_login_started = False
            return

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
                self.status_pill.set_status("已取消", "idle")
                with self._login_lock:
                    self.login_in_progress = False
                    self.pending_ticket = ""
                return

        # 抢码加速：跳过 roleInfos 校验，直接 scanLogin，省一次 RTT
        # （约 100-400ms）。失败时 scanLogin 自带错误码，代价只是报错
        # 文案不如 roleInfos 精确。可通过 live_skip_role_check 关闭。
        skip_role = bool(config_manager.get("live_skip_role_check", True))
        self.scan_thread = ScanThread(qr_code, skip_role_check=skip_role)
        self.scan_thread.scan_result.connect(self.on_scan_result)
        self.scan_thread.log_message.connect(self.add_log)
        self.scan_thread.start()

    def on_scan_result(self, result):
        """扫码结果回调"""
        from utils.grab_stats import grab_stats
        grab_stats.record_login_result(bool(result.get("success")))
        if result.get("success"):
            self.login_in_progress = False
            self.pending_ticket = ""
            self.add_log("扫码成功！")
            self.status_pill.set_status("登录成功", "idle")

            # #8 窗口前置
            self._bring_to_front()

            QMessageBox.information(self, "成功", "扫码登录成功！")

            # 停止所有扫描
            self._stop_all_scanners()

            # #3 自动退出
            # M4修复：PySide6 的 slot 包装器会吞掉 SystemExit，sys.exit(0)
            # 可能退不出；用 QApplication.quit() 可靠退出
            if config_manager.get("auto_exit", False):
                self.add_log("自动退出已启用，3秒后退出...")
                QTimer.singleShot(3000, QApplication.instance().quit)

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

            SmsDialog = _get_dialog_class('SmsDialog')
            sms_dlg = SmsDialog(token_for_sms, mobile, self)
            if sms_dlg.exec() == SmsDialog.Rejected:
                self.add_log("用户取消验证")
                self.status_pill.set_status("已取消", "idle")
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

            # Token 过期 → 同步账号状态，并指引一键续期
            if "Token已过期" in message and self.selected_account_index >= 0:
                row = self.selected_account_index
                account_manager.set_account_status(row, "过期", "Token已过期")
                self._update_account_status_cell(row, "过期")
                self.add_log("💡 提示：右键该账号 → 🔄 重新获取Token，可一键续期")

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
                QMessageBox.warning(self, "提示", "登录已过期，右键该账号 → 重新获取Token 可一键续期！")

            # 只在窗口可见时重置：右键关闭扫码窗后引用不会置 None，
            # 无守卫会在隐藏窗口上重启定时器，造成"幽灵截图+幽灵登录"
            if self.scan_window and not self.scan_window.isHidden():
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
        # U2优化：datetime 提顶层，避免高频调用重复 import
        timestamp = datetime.now().strftime("%H:%M:%S")
        self.log_text.append(f"[{timestamp}] {message}")
        # 优化61：上限 1000 行，超了删旧的（防长时运行卡顿）
        try:
            doc = self.log_text.document()
            if doc.blockCount() > 1000:
                cursor = self.log_text.textCursor()
                cursor.movePosition(cursor.MoveMode.Start)
                cursor.movePosition(
                    cursor.MoveMode.Down, cursor.MoveMode.KeepAnchor,
                    doc.blockCount() - 1000,
                )
                cursor.removeSelectedText()
        except Exception:
            pass
        scrollbar = self.log_text.verticalScrollBar()
        scrollbar.setValue(scrollbar.maximum())

    def show_performance_stats(self):
        if not PERF_MONITOR_AVAILABLE:
            QMessageBox.information(self, "性能统计", "性能监控系统未可用")
            return
        stats_summary = perf_monitor.get_statistics_summary()
        method_distribution = perf_monitor.get_method_distribution()
        full_info = stats_summary + "\n\n" + method_distribution
        self.add_log("\n" + stats_summary)
        QMessageBox.information(self, "性能统计", full_info)

    # ==================================================================
    # Close
    # ==================================================================

    def closeEvent(self, event):
        self._stop_all_scanners()
        # 等工作线程真正退出，避免 "QThread: Destroyed while thread is
        # still running" 导致退出时崩溃。有界等待：worker 不依赖 UI 线程，
        # 不会死锁；超时则放行，daemon 线程由解释器回收。
        try:
            if self.live_scanner:
                self.live_scanner.wait(5000)
            if self.scan_thread:
                self.scan_thread.wait(5000)
            for t in self.account_check_threads:
                try:
                    t.wait(3000)
                except Exception:
                    pass
            if self.short_link_thread:
                try:
                    self.short_link_thread.wait(9000)
                except Exception:
                    pass
        except Exception:
            pass
        try:
            from utils.ai_qr_scanner import ai_qr_scanner as _scanner
            _scanner.shutdown()
            # 优化60：回收子进程（IsolatedDecoder 若启用）
            try:
                _dec = getattr(_scanner, "_isolated_decoder", None)
                if _dec is not None:
                    _dec.shutdown()
            except Exception:
                pass
        except Exception:
            pass
        # 优化57+58：kill 所有 QTimer，防泄漏
        try:
            for timer in self.findChildren(QTimer):
                try:
                    timer.stop()
                except Exception:
                    pass
        except Exception:
            pass
        # 优化65：保存窗口位置
        try:
            from utils.config_manager import config_manager as _cm_geo2
            _cm_geo2.set("window_pos", [self.x(), self.y()])
        except Exception:
            pass
        event.accept()
