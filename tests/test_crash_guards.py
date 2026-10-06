# -*- coding: utf-8 -*-
"""
Regression tests for issue #8 (screen-scan hard crash).

Covers the native-crash candidate guards:
  1. Degenerate images (empty / 0-width / 0-height) are rejected before
     reaching WeChatQR / Caffe dnn.
  2. Empty scan regions are rejected before screenshotting.
  3. The QTimer scan callback isolates Python exceptions so one bad scan
     cannot take down the Qt event loop.
  4. Crash diagnostics install cleanly (faulthandler + excepthooks).
"""
import os
import sys
import threading

import numpy as np
import pytest
from unittest.mock import patch

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication
from PySide6.QtCore import QRect


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


class TestDegenerateImageGuards:
    """Empty / 0-size images must never reach the native decoders."""

    def test_try_decode_array_rejects_empty(self):
        from utils.ai_qr_scanner import ai_qr_scanner

        assert (
            ai_qr_scanner.try_decode_array(
                np.zeros((0, 100, 3), dtype=np.uint8)
            )
            is None
        )
        assert (
            ai_qr_scanner.try_decode_array(
                np.zeros((100, 0, 3), dtype=np.uint8)
            )
            is None
        )
        assert ai_qr_scanner.try_decode_array(None) is None

    def test_qr_scanner_rejects_empty_region(self):
        from utils.qr_scanner import qr_scanner

        assert qr_scanner.scan_region(10, 10, 0, 100) is None
        assert qr_scanner.scan_region(10, 10, 100, 0) is None
        assert qr_scanner.scan_region(10, 10, -5, 100) is None


class TestScanWindowRobustness:
    """The QTimer callback must survive decode failures."""

    def test_scan_callback_isolates_decode_exception(self):
        from ui import scan_window as sw_mod
        from ui.scan_window import ScanWindow

        win = ScanWindow()
        try:
            with patch.object(
                sw_mod.qr_scanner,
                "scan_region",
                side_effect=RuntimeError("boom"),
            ):
                win.scan_qr_code()  # must not raise
        finally:
            win.close()

    def test_zero_size_geometry_skips_scan(self):
        from ui import scan_window as sw_mod
        from ui.scan_window import ScanWindow, ScanWindow as SW

        win = ScanWindow()
        try:
            with patch.object(
                SW, "geometry", return_value=QRect(0, 0, 0, 0)
            ), patch.object(sw_mod.qr_scanner, "scan_region") as m:
                win.scan_qr_code()
                m.assert_not_called()
        finally:
            win.close()


class TestCrashDiagnostics:
    """main.install_crash_handlers() must install without side effects."""

    def test_install_crash_handlers(self):
        import main as main_mod

        old_hook = sys.excepthook
        old_thread_hook = threading.excepthook
        try:
            main_mod.install_crash_handlers()
            assert os.path.basename(main_mod.crash_log_path()) == "crash.log"
            assert sys.excepthook is not old_hook
            assert threading.excepthook is not old_thread_hook
        finally:
            sys.excepthook = old_hook
            threading.excepthook = old_thread_hook
            try:
                import faulthandler

                faulthandler.disable()
            except Exception:
                pass
