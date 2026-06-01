# -*- coding: utf-8 -*-
"""
Regression tests for LiveStreamScanner.

Covers three known bugs in the live-stream monitoring path:
  1. Stream interruption causes immediate exit with no reconnect attempt.
  2. stop() only sets a flag – if cap.read() blocks, the thread hangs.
  3. QR codes shorter than 24 characters are silently dropped.
"""
import sys
import os
import time
import threading
from unittest.mock import patch

import pytest

# Ensure the project root is on sys.path so `utils.*` imports resolve.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtCore import QCoreApplication, Qt
from PySide6.QtWidgets import QApplication
from utils.live_stream_scanner import LiveStreamScanner


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture(scope="session", autouse=True)
def qapp():
    """A single QApplication shared across all tests (required by Qt)."""
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _process_events():
    """Flush pending Qt events so cross-thread signals are delivered."""
    QCoreApplication.processEvents()


class FakeCapture:
    """Minimal stand-in for cv2.VideoCapture.

    Parameters
    ----------
    frames : list[tuple[bool, object]]
        Sequence of (ret, frame) tuples that ``read()`` will yield.
        After the sequence is exhausted every subsequent read returns
        ``(False, None)``.
    open_ok : bool
        What ``isOpened()`` returns.
    block_on_read : bool
        If True, ``read()`` blocks until ``release()`` is called.
    """

    def __init__(self, frames=None, open_ok=True, block_on_read=False):
        self._frames = list(frames or [])
        self._idx = 0
        self._open = open_ok
        self._block_on_read = block_on_read
        self._block_event = threading.Event()
        self._released = False
        self._entered_read = threading.Event()
        self.read_count = 0

    def isOpened(self):
        return self._open

    def read(self):
        self.read_count += 1
        if self._block_on_read and not self._released:
            self._entered_read.set()
            # Simulate a blocking network read – only unblocked by release()
            self._block_event.wait(timeout=30)
            return (False, None)
        if self._idx < len(self._frames):
            ret, frame = self._frames[self._idx]
            self._idx += 1
            return ret, frame
        return (False, None)

    def release(self):
        self._released = True
        self._block_event.set()  # unblock any pending read()

    def wait_until_read_entered(self, timeout=5):
        """Block the caller until ``read()`` has been entered at least once."""
        return self._entered_read.wait(timeout=timeout)


def _make_dummy_frame():
    """Return a small numpy array that looks like a BGR video frame."""
    import numpy as np
    return np.zeros((100, 100, 3), dtype=np.uint8)


# ---------------------------------------------------------------------------
# Bug 1 – Stream interruption causes immediate exit (no reconnect)
# ---------------------------------------------------------------------------

class TestStreamReconnection:
    """The scanner should retry on transient stream failures."""

    def test_reconnects_after_transient_read_failure(self):
        """If cap.read() returns (False, None) once, the scanner should
        attempt to reopen the stream rather than exit immediately."""

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        status_msgs: list[str] = []
        errors: list[str] = []
        scanner.status_changed.connect(
            status_msgs.append, Qt.ConnectionType.DirectConnection
        )
        scanner.error_occurred.connect(
            errors.append, Qt.ConnectionType.DirectConnection
        )

        dummy = _make_dummy_frame()
        # First capture: a few good frames then a failure
        first_cap = FakeCapture(
            frames=[(True, dummy)] * 5 + [(False, None)],
            open_ok=True,
        )
        # Second capture (after reconnect): good frames then end
        second_cap = FakeCapture(
            frames=[(True, dummy)] * 10 + [(False, None)],
            open_ok=True,
        )
        # Third capture (for reconnect after second_cap exhausts)
        third_cap = FakeCapture(frames=[], open_ok=False)
        caps = iter([first_cap, second_cap, third_cap])

        with patch("cv2.VideoCapture", side_effect=lambda url: next(caps)):
            with patch.object(scanner, "_scan_frame", return_value=None):
                with patch("utils.live_stream_scanner.time.sleep"):
                    scanner.start()
                    scanner.wait(5000)

        _process_events()

        assert second_cap.read_count > 0, (
            "Scanner did not reconnect after stream interruption"
        )
        reconnect_msgs = [
            m for m in status_msgs if "重连" in m or "reconnect" in m.lower()
        ]
        assert len(reconnect_msgs) > 0, (
            f"No reconnection status emitted. Status messages: {status_msgs}"
        )


# ---------------------------------------------------------------------------
# Bug 2 – stop() doesn't terminate when cap.read() blocks
# ---------------------------------------------------------------------------

class TestStopTermination:
    """stop() must actually terminate the scanner within a reasonable time,
    even when the underlying capture is blocking on a network read."""

    def test_stop_unblocks_hanging_read(self):
        fake_cap = FakeCapture(block_on_read=True, open_ok=True)

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        with patch("cv2.VideoCapture", return_value=fake_cap):
            scanner.start()
            # Wait until the thread has entered the blocking read()
            entered = fake_cap.wait_until_read_entered(timeout=5)
            assert entered, "Thread never entered cap.read()"

            scanner.stop()
            finished = scanner.wait(2000)

        assert finished, (
            "Scanner thread did not terminate within 2 s after stop() – "
            "cap.read() is likely still blocking because stop() does not "
            "release the capture"
        )


# ---------------------------------------------------------------------------
# Bug 3 – Short QR codes silently dropped
# ---------------------------------------------------------------------------

class TestShortQRCodeHandling:
    """QR codes shorter than 24 characters must still be emitted."""

    def test_short_qr_code_is_emitted(self):
        dummy = _make_dummy_frame()
        short_qr = "KURO#SHORT"  # 10 chars, well under 24

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 10 + [(False, None)],
            open_ok=True,
        )

        with patch("cv2.VideoCapture", return_value=fake_cap):
            with patch.object(scanner, "_scan_frame", return_value=short_qr):
                scanner.start()
                scanner.wait(5000)

        _process_events()

        assert short_qr in detected, (
            f"Short QR code ({short_qr!r}) was not emitted. "
            f"Detected codes: {detected}"
        )

    def test_long_qr_code_still_works(self):
        dummy = _make_dummy_frame()
        long_qr = "https://example.com/G152#KURO_ticket_abcdef123456"

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 10 + [(False, None)],
            open_ok=True,
        )

        with patch("cv2.VideoCapture", return_value=fake_cap):
            with patch.object(scanner, "_scan_frame", return_value=long_qr):
                scanner.start()
                scanner.wait(5000)

        _process_events()

        assert long_qr in detected, (
            f"Long QR code was not emitted. Detected: {detected}"
        )

    def test_duplicate_short_qr_not_emitted_twice(self):
        """Even short codes must be de-duplicated."""
        dummy = _make_dummy_frame()
        short_qr = "KURO#SHORT"

        scanner = LiveStreamScanner()
        scanner.set_stream_url("http://fake-stream.test/live.flv", "bilibili")

        detected: list[str] = []
        scanner.qr_detected.connect(
            detected.append, Qt.ConnectionType.DirectConnection
        )

        fake_cap = FakeCapture(
            frames=[(True, dummy)] * 30 + [(False, None)],
            open_ok=True,
        )

        with patch("cv2.VideoCapture", return_value=fake_cap):
            with patch.object(scanner, "_scan_frame", return_value=short_qr):
                scanner.start()
                scanner.wait(5000)

        _process_events()

        assert detected.count(short_qr) == 1, (
            f"Short QR code emitted {detected.count(short_qr)} times, expected 1"
        )
