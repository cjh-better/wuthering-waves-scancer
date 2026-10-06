# -*- coding: utf-8 -*-
"""
Tests for the unified decode contract (ImageDecoder):
``decode(image) -> str | None`` on both QRScanner and AIQRScanner.
"""
import os
import sys

import numpy as np
import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.qr_scanner import ImageDecoder, qr_scanner


class TestDecodeContract:
    def test_qr_scanner_implements_contract(self):
        assert isinstance(qr_scanner, ImageDecoder)

    def test_ai_scanner_implements_contract(self):
        from utils.ai_qr_scanner import ai_qr_scanner

        assert isinstance(ai_qr_scanner, ImageDecoder)

    def test_decode_none_returns_none(self):
        assert qr_scanner.decode(None) is None

    def test_decode_empty_array_returns_none(self):
        assert qr_scanner.decode(np.zeros((0, 10, 3), dtype=np.uint8)) is None

    def test_decode_blank_image_returns_none(self):
        img = Image.new("RGB", (64, 64), "white")
        assert qr_scanner.decode(img) is None

    def test_decode_never_raises(self):
        assert qr_scanner.decode(object()) is None
        assert qr_scanner.decode("not an image") is None

    def test_ai_decode_dispatches_ndarray(self):
        """AIQRScanner.decode routes ndarrays through try_decode_array."""
        from utils.ai_qr_scanner import AIQRScanner

        scanner = AIQRScanner.__new__(AIQRScanner)  # skip heavy __init__
        called = {}

        def fake_try_decode_array(arr, color="BGR", allow_slow_fallback=True):
            called["color"] = color
            called["shape"] = getattr(arr, "shape", None)
            return "TICKET"

        scanner.try_decode_array = fake_try_decode_array
        result = scanner.decode(np.zeros((10, 10, 3), dtype=np.uint8))
        assert result == "TICKET"
        assert called["color"] == "BGR"
        assert called["shape"] == (10, 10, 3)

    def test_ai_decode_dispatches_pil(self):
        from utils.ai_qr_scanner import AIQRScanner

        scanner = AIQRScanner.__new__(AIQRScanner)
        scanner.try_decode_qr = lambda img, allow_slow_fallback=True: "TICKET2"
        result = scanner.decode(Image.new("RGB", (10, 10), "white"))
        assert result == "TICKET2"
