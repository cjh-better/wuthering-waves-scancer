# -*- coding: utf-8 -*-
"""
鸣潮抢码器 - 主程序入口
"""
import faulthandler
import sys
import os
import tempfile
import threading
import traceback
from PySide6.QtWidgets import QApplication
from PySide6.QtCore import Qt
from PySide6.QtGui import QIcon
from ui.main_window import MainWindow


# faulthandler 的输出文件句柄：进程级持有，避免被 GC 关闭
_crash_log_file = None


def crash_log_path() -> str:
    """崩溃日志路径（供 README/issue 模板引用）。"""
    try:
        log_dir = os.path.join(tempfile.gettempdir(), "wuthering-waves-scancer")
        os.makedirs(log_dir, exist_ok=True)
        return os.path.join(log_dir, "crash.log")
    except Exception:
        return os.path.join(tempfile.gettempdir(), "ww-scancer-crash.log")


def _append_crash_log(header: str, body: str) -> None:
    try:
        with open(crash_log_path(), "a", encoding="utf-8", errors="replace") as f:
            f.write("\n===== %s =====\n%s\n" % (header, body))
    except Exception:
        pass


def install_crash_handlers() -> None:
    """安装崩溃诊断：未捕获异常 + 线程异常 + native 崩溃全部落盘。

    解决"闪退无信息"类问题（issue #8）：用户只需把 crash.log 贴到
    issue 里即可定位，不再靠猜。
    """
    global _crash_log_file
    path = crash_log_path()

    # native 崩溃（segfault/abort）：faulthandler 直接 dump C 层堆栈
    try:
        _crash_log_file = open(path, "a", encoding="utf-8", errors="replace")
        faulthandler.enable(file=_crash_log_file)
    except Exception:
        pass

    # 主线程未捕获异常
    _default_excepthook = sys.excepthook

    def _excepthook(exc_type, exc_value, exc_tb):
        _append_crash_log(
            "uncaught exception",
            "".join(traceback.format_exception(exc_type, exc_value, exc_tb)),
        )
        _default_excepthook(exc_type, exc_value, exc_tb)

    sys.excepthook = _excepthook

    # 工作线程未捕获异常
    def _thread_excepthook(args):
        _append_crash_log(
            "uncaught thread exception",
            "".join(
                traceback.format_exception(
                    args.exc_type, args.exc_value, args.exc_traceback
                )
            ),
        )

    threading.excepthook = _thread_excepthook


def main():
    """主函数"""
    # 优化75：单实例锁——防止多开抢 DXGI/摄像头资源
    import tempfile as _tf
    import os as _os
    _lock_path = _os.path.join(_tf.gettempdir(), "wuthering_scancer.lock")
    try:
        import fcntl as _fcntl
        _lock_f = open(_lock_path, "w")
        _fcntl.flock(_lock_f, _fcntl.LOCK_EX | _fcntl.LOCK_NB)
    except ImportError:
        # Windows：用 msvcrt
        try:
            import msvcrt as _msvcrt
            _lock_f = open(_lock_path, "w")
            _msvcrt.locking(_lock_f.fileno(), _msvcrt.LK_NBLCK, 1)
        except Exception:
            _lock_f = None
    except Exception:
        # 已有实例在运行
        print("已有实例在运行，退出。")
        try:
            from PySide6.QtWidgets import QApplication, QMessageBox
            _app = QApplication([])
            QMessageBox.warning(None, "提示", "鸣潮抢码器已在运行中，无需多开。")
        except Exception:
            pass
        return
    install_crash_handlers()
    # 崩溃恢复：启动时清除 clean 标记（正常退出会重写）
    try:
        from utils.crash_recovery import clear_clean_exit
        clear_clean_exit()
    except Exception:
        pass
    try:
        # 优化80：启动分阶段计时（定位慢启动）
        import time as _t
        _t0 = _t.time()
        from utils.log import get_logger
        _mlog = get_logger("Main")
        _mlog.info("[Startup] 阶段1: 基础初始化 %.0fms", (_t.time() - _t0) * 1000)
        _mlog.info(
            "崩溃日志路径：%s（闪退时请把此文件贴到 issue）", crash_log_path()
        )
        # 打包资源完整性自检（模型缺失 → 明确告警 + 降级，不闪退）
        from utils.resources import log_resource_status
        log_resource_status()
        _mlog.info("[Startup] 阶段2: 资源自检 %.0fms", (_t.time() - _t0) * 1000)
    except Exception:
        pass

    # 启用高DPI支持
    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )
    QApplication.setAttribute(Qt.AA_EnableHighDpiScaling)
    QApplication.setAttribute(Qt.AA_UseHighDpiPixmaps)
    
    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("鸣潮抢码器")
    app.setOrganizationName("WutheringWaves")
    
    # 设置应用程序图标
    icon_path = "11409B.png"
    # 打包后图标在根目录
    if not os.path.exists(icon_path) and hasattr(sys, '_MEIPASS'):
        icon_path = os.path.join(sys._MEIPASS, '11409B.png')
    if os.path.exists(icon_path):
        app.setWindowIcon(QIcon(icon_path))
    
    # 创建主窗口
    window = MainWindow()
    window.show()
    
    # 运行应用；正常退出时写 clean 标记（崩溃时写不到，下次启动可识别）
    try:
        from utils.crash_recovery import mark_clean_exit
        app.aboutToQuit.connect(mark_clean_exit)
    except Exception:
        pass
    # 长时内存监控（后台线程，7×24 挂机泄漏预警）
    try:
        from utils.memory_monitor import memory_monitor
        memory_monitor.start()
        app.aboutToQuit.connect(memory_monitor.stop)
    except Exception:
        pass
    sys.exit(app.exec())


if __name__ == "__main__":
    main()

