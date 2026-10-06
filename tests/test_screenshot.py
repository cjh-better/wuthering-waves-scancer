# -*- coding: utf-8 -*-
"""Tests for the screenshot backend abstraction (utils.screenshot)."""
import os
import sys

import pytest
from PIL import Image

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils.screenshot import (
    PILBackend,
    ScreenshotBackend,
    available_backends,
    grab_region_first_success,
)


class TestPILBackend:
    def test_implements_contract(self):
        assert isinstance(PILBackend(), ScreenshotBackend)

    def test_degenerate_region_returns_none(self):
        backend = PILBackend()
        assert backend.grab_region(0, 0, 0, 100) is None
        assert backend.grab_region(0, 0, 100, 0) is None


class TestAvailableBackends:
    def test_chain_always_ends_with_pil(self):
        chain = available_backends()
        assert len(chain) >= 1
        assert chain[-1].name == "PIL"

    def test_no_duplicate_names(self):
        chain = available_backends()
        names = [b.name for b in chain]
        assert len(names) == len(set(names))


class _FailingBackend:
    name = "FAIL"

    def grab_region(self, x, y, width, height):
        raise RuntimeError("boom")


class _OkBackend:
    name = "OK"

    def __init__(self, img):
        self._img = img

    def grab_region(self, x, y, width, height):
        return self._img


class TestGrabRegionFirstSuccess:
    def test_skips_failing_backends(self):
        img = Image.new("RGB", (4, 4), "white")
        result, name = grab_region_first_success(
            [_FailingBackend(), _OkBackend(img)], 0, 0, 4, 4
        )
        assert result is img
        assert name == "OK"

    def test_all_fail_returns_unknown(self):
        result, name = grab_region_first_success([_FailingBackend()], 0, 0, 4, 4)
        assert result is None
        assert name == "unknown"

    def test_none_result_continues_chain(self):
        img = Image.new("RGB", (4, 4), "white")

        class _NoneBackend:
            name = "NONE"

            def grab_region(self, x, y, width, height):
                return None

        result, name = grab_region_first_success(
            [_NoneBackend(), _OkBackend(img)], 0, 0, 4, 4
        )
        assert result is img
        assert name == "OK"
