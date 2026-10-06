# -*- coding: utf-8 -*-
"""Tests for utils.resources (packaging resource integrity check)."""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import resources
from utils.resources import (
    MODEL_FILES,
    check_resources,
    model_dir,
    model_paths,
    resource_base,
)


class TestResourceBase:
    def test_model_paths_has_all_files(self):
        paths = model_paths()
        assert set(paths.keys()) == set(MODEL_FILES)
        for p in paths.values():
            assert p.startswith(model_dir())

    def test_repo_has_models(self):
        # The repo ships ScanModel/ – integrity check must pass here.
        assert check_resources() == []

    def test_missing_model_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            resources, "model_dir", lambda: str(tmp_path / "ScanModel")
        )
        (tmp_path / "ScanModel").mkdir()
        problems = check_resources()
        assert len(problems) == len(MODEL_FILES)
        assert any("detect.caffemodel" in p for p in problems)

    def test_missing_dir_reported(self, tmp_path, monkeypatch):
        monkeypatch.setattr(
            resources, "model_dir", lambda: str(tmp_path / "nope")
        )
        problems = check_resources()
        assert any("ScanModel" in p for p in problems)

    def test_empty_file_reported(self, tmp_path, monkeypatch):
        d = tmp_path / "ScanModel"
        d.mkdir()
        for name in MODEL_FILES:
            (d / name).write_bytes(b"x")
        (d / MODEL_FILES[0]).write_bytes(b"")  # empty it
        monkeypatch.setattr(resources, "model_dir", lambda: str(d))
        problems = check_resources()
        assert any("为空" in p for p in problems)

    def test_resource_base_is_repo_root_in_dev(self):
        # Not frozen here: base should be the repo root containing main.py.
        assert os.path.isfile(os.path.join(resource_base(), "main.py"))


class TestLazyModelLoading:
    def test_ensure_models_is_idempotent(self):
        """_ensure_models loads at most once (double-checked locking)."""
        from utils.ai_qr_scanner import AIQRScanner

        scanner = AIQRScanner.__new__(AIQRScanner)
        scanner._models_loaded = False
        import threading

        scanner._models_lock = threading.Lock()
        calls = []
        scanner._load_ai_models = lambda: calls.append(1)
        scanner._init_wechat_detector = lambda: calls.append(2)

        import utils.ai_qr_scanner as mod

        old = mod.OPENCV_AVAILABLE
        mod.OPENCV_AVAILABLE = True
        try:
            scanner._ensure_models()
            scanner._ensure_models()
        finally:
            mod.OPENCV_AVAILABLE = old
        assert calls == [1, 2]  # loaded exactly once

    def test_ensure_models_skipped_without_opencv(self):
        from utils.ai_qr_scanner import AIQRScanner

        scanner = AIQRScanner.__new__(AIQRScanner)
        scanner._models_loaded = False
        import threading

        scanner._models_lock = threading.Lock()
        scanner._load_ai_models = lambda: (_ for _ in ()).throw(
            AssertionError("must not be called")
        )
        import utils.ai_qr_scanner as mod

        old = mod.OPENCV_AVAILABLE
        mod.OPENCV_AVAILABLE = False
        try:
            scanner._ensure_models()  # must not raise, must not load
        finally:
            mod.OPENCV_AVAILABLE = old
        assert scanner._models_loaded is False
