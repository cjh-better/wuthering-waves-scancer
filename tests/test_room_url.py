# -*- coding: utf-8 -*-
"""Tests for utils/room_url.py -- share-link to room ID resolution."""
import os
import sys
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from utils import room_url


class TestExtractRoomId:
    def test_pure_digits(self):
        assert room_url.extract_room_id("7318296342388083201", "douyin") == "7318296342388083201"

    def test_douyin_full_url(self):
        assert room_url.extract_room_id("https://live.douyin.com/123456", "douyin") == "123456"

    def test_douyin_room_id_param(self):
        url = "https://live.douyin.com/?room_id=7318296342388083201"
        assert room_url.extract_room_id(url, "douyin") == "7318296342388083201"

    def test_bilibili_full_url(self):
        assert room_url.extract_room_id("https://live.bilibili.com/21452505", "bilibili") == "21452505"

    def test_fallback_digits_in_text(self):
        assert room_url.extract_room_id("room 99991234", "douyin") == "99991234"

    def test_garbage_returns_empty(self):
        assert room_url.extract_room_id("abc", "douyin") == ""

    def test_empty_returns_empty(self):
        assert room_url.extract_room_id("", "douyin") == ""

    def test_share_text_with_embedded_url(self):
        text = "【抖音】快来看直播吧 https://live.douyin.com/7654321 复制此链接"
        assert room_url.extract_room_id(text, "douyin") == "7654321"

    def test_short_link_not_directly_extractable(self):
        assert room_url.extract_room_id("https://v.douyin.com/iR2n3abc/", "douyin") == ""


class TestFindShortLink:
    def test_douyin_short_link(self):
        assert room_url.find_short_link("https://v.douyin.com/iR2n3abc/") == "https://v.douyin.com/iR2n3abc/"

    def test_bilibili_short_link(self):
        assert room_url.find_short_link("https://b23.tv/ab12Cd") == "https://b23.tv/ab12Cd"

    def test_short_link_inside_share_text(self):
        text = "分享给你一个直播间 https://v.douyin.com/iR2n3abc/ 快来围观"
        assert room_url.find_short_link(text) == "https://v.douyin.com/iR2n3abc/"

    def test_full_url_is_not_short_link(self):
        assert room_url.find_short_link("https://live.douyin.com/123456") is None

    def test_no_url_returns_none(self):
        assert room_url.find_short_link("7318296342388083201") is None


def _mock_session(final_url=None, head_ok=True):
    session = MagicMock()
    head_resp = MagicMock()
    head_resp.url = final_url if head_ok else "https://v.douyin.com/iR2n3abc/"
    session.head.return_value = head_resp
    get_resp = MagicMock()
    get_resp.url = final_url or ""
    session.get.return_value = get_resp
    return session


class TestResolveRoomId:
    def test_resolve_via_head_redirect(self):
        session = _mock_session("https://live.douyin.com/99887766")
        with patch("utils.room_url.new_session", return_value=session):
            assert room_url.resolve_room_id("https://v.douyin.com/iR2n3abc/", "douyin") == "99887766"

    def test_resolve_falls_back_to_get(self):
        session = _mock_session("https://live.bilibili.com/22334455", head_ok=False)
        session.head.side_effect = Exception("HEAD not allowed")
        with patch("utils.room_url.new_session", return_value=session):
            assert room_url.resolve_room_id("https://b23.tv/ab12Cd", "bilibili") == "22334455"

    def test_resolve_no_room_id_in_final_url(self):
        session = _mock_session("https://www.douyin.com/")
        with patch("utils.room_url.new_session", return_value=session):
            assert room_url.resolve_room_id("https://v.douyin.com/iR2n3abc/", "douyin") == ""

    def test_resolve_network_failure_returns_empty(self):
        session = MagicMock()
        session.head.side_effect = Exception("timeout")
        session.get.side_effect = Exception("timeout")
        with patch("utils.room_url.new_session", return_value=session):
            assert room_url.resolve_room_id("https://v.douyin.com/iR2n3abc/", "douyin") == ""
