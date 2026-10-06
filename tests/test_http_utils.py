# -*- coding: utf-8 -*-
"""Tests for utils.http shared helpers."""
import os
import sys
from unittest.mock import MagicMock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import http as http_utils


class TestSafeJson:
    def test_valid(self):
        assert http_utils.safe_json('{"code": 0}') == {"code": 0}

    def test_invalid_returns_none(self):
        assert http_utils.safe_json("") is None
        assert http_utils.safe_json("{invalid") is None
        assert http_utils.safe_json("<html>error</html>") is None

    def test_non_string_returns_none(self):
        assert http_utils.safe_json(None) is None
        assert http_utils.safe_json(123) is None
        assert http_utils.safe_json(b'{"a": 1}') is None


class TestDiagResponse:
    def test_never_raises(self):
        resp = MagicMock()
        resp.status_code = 200
        resp.text = "x" * 500
        http_utils.diag_response("tag", resp)  # must not raise

    def test_broken_response_never_raises(self):
        resp = MagicMock()
        resp.status_code = 500
        type(resp).text = property(lambda self: (_ for _ in ()).throw(ValueError()))
        http_utils.diag_response("tag", resp)  # must not raise


class TestNewSession:
    def test_returns_session(self):
        import requests

        s = http_utils.new_session()
        assert isinstance(s, requests.Session)
