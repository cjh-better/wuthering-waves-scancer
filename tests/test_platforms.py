# -*- coding: utf-8 -*-
"""
Tests for the platform adapters (utils.platforms).

Covers the refactored Douyin flow (room page -> HTML extraction ->
signed web/enter API) and the StreamError classification.
"""
import json
import os
import sys
import urllib.parse
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from PySide6.QtWidgets import QApplication

from utils.platforms import (
    BilibiliAdapter,
    DouyinAdapter,
    LiveStreamInfo,
    LiveStreamStatus,
    StreamError,
    get_adapter,
)
from utils.platforms import douyin as douyin_module


@pytest.fixture(scope="session", autouse=True)
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    yield app


def _http_resp(status_code: int, text: str):
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    return resp


_HTML_WITH_FLV = (
    "<html><body><script>window.DATA=\""
    '{\\"stream_url\\":{\\"live_core_sdk_data\\":{\\"pull_data\\":'
    '{\\"stream_data\\":\\"{\\\\\\"data\\\\\\":{\\\\\\"origin\\\\\\":'
    '{\\\\\\"main\\\\\\":{\\\\\\"flv\\\\\\":\\\\\\"'
    "https://pull-hs-f123.douyincdn.com/third/stream.flv"
    '\\"}}}}}\\"}}}"'
    "</script></body></html>"
)
_EXPECTED_FLV = "https://pull-hs-f123.douyincdn.com/third/stream.flv"
_HTML_WITHOUT_STREAM = (
    "<html><body><script>window.DATA=\"{\\\"room_id\\\":\\\"123456\\\"}\";</script>"
    "</body></html>"
)


def _api_ok(flv_url: str):
    return _http_resp(
        200,
        json.dumps(
            {
                "status_code": 0,
                "data": {
                    "data": [
                        {
                            "status": 2,
                            "stream_url": {
                                "live_core_sdk_data": {
                                    "pull_data": {
                                        "stream_data": json.dumps(
                                            {
                                                "data": {
                                                    "origin": {
                                                        "main": {"flv": flv_url}
                                                    }
                                                }
                                            }
                                        )
                                    }
                                }
                            },
                        }
                    ]
                },
            }
        ),
    )


class TestGetAdapter:
    def test_known_platforms(self):
        session = MagicMock()
        assert isinstance(get_adapter("bilibili", session), BilibiliAdapter)
        assert isinstance(get_adapter("douyin", session), DouyinAdapter)

    def test_unknown_platform(self):
        assert get_adapter("tiktok", MagicMock()) is None


class TestStreamError:
    def test_describe_defaults(self):
        assert "风控" in StreamError.describe(StreamError.EMPTY_RESPONSE)
        assert StreamError.describe(StreamError.NONE) == ""

    def test_describe_with_extra(self):
        text = StreamError.describe(StreamError.HTTP_ERROR, "(HTTP 403)")
        assert "HTTP 403" in text


class TestBilibiliAdapter:
    def test_fetch_normal(self):
        session = MagicMock()
        session.get.side_effect = [
            _http_resp(
                200,
                json.dumps(
                    {"code": 0, "data": {"live_status": 1, "room_id": 7734200}}
                ),
            ),
            _http_resp(
                200,
                json.dumps(
                    {
                        "data": {
                            "playurl_info": {
                                "playurl": {
                                    "stream": [
                                        {
                                            "format": [
                                                {
                                                    "codec": [
                                                        {
                                                            "base_url": "/live/b.flv",
                                                            "url_info": [
                                                                {
                                                                    "host": "https://h.test",
                                                                    "extra": "?t=1",
                                                                }
                                                            ],
                                                        }
                                                    ]
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    }
                ),
            ),
        ]
        info = BilibiliAdapter(session).fetch("6")
        assert info.status == LiveStreamStatus.Normal
        assert info.url == "https://h.test/live/b.flv?t=1"
        assert info.error == StreamError.NONE

    def test_fetch_absent_carries_enum(self):
        session = MagicMock()
        session.get.return_value = _http_resp(
            200, json.dumps({"code": 60004, "data": {}})
        )
        info = BilibiliAdapter(session).fetch("999")
        assert info.status == LiveStreamStatus.Absent
        assert info.error == StreamError.ABSENT
        assert "房间不存在" in info.detail


class TestDouyinAdapter:
    def setup_method(self):
        from utils.platforms.douyin import DouyinAdapter
        DouyinAdapter.reset_api_health()
        from utils.platforms.base import clear_stream_url_cache
        clear_stream_url_cache()

    def test_room_page_with_stream_skips_api(self):
        """HTML-first: stream found on the room page, API never called."""
        session = MagicMock()
        session.get.return_value = _http_resp(200, _HTML_WITH_FLV)
        info = DouyinAdapter(session).fetch("123456")
        assert info.status == LiveStreamStatus.Normal
        assert info.url == _EXPECTED_FLV
        assert session.get.call_count == 1
        first_url = session.get.call_args_list[0][0][0]
        assert "web/enter" not in first_url

    def test_signed_api_called_when_html_has_no_stream(self):
        """Room page has no stream -> signed web/enter API is queried."""
        session = MagicMock()
        session.get.side_effect = [
            _http_resp(200, _HTML_WITHOUT_STREAM),  # room page (ttwid + HTML)
            _api_ok(_EXPECTED_FLV),  # signed API
        ]
        info = DouyinAdapter(session).fetch("123456")
        assert info.status == LiveStreamStatus.Normal
        assert info.url == _EXPECTED_FLV

        api_url = session.get.call_args_list[1][0][0]
        assert "a_bogus=" in api_url  # signature appended
        query = urllib.parse.urlparse(api_url).query
        assert "msToken=" in query  # empty but present (verified recipe)
        assert "web_rid=123456" in query

        api_headers = session.get.call_args_list[1][1]["headers"]
        assert api_headers["Referer"] == "https://live.douyin.com/123456"
        # The UA used for signing must equal the request UA.
        assert "QQBrowser" in api_headers["User-Agent"]

    def test_ttwid_comes_from_server_cookie(self):
        """Documents the mechanism: the room-page GET populates the
        shared session's cookie jar, so the API call carries ttwid."""
        import requests

        jar_session = requests.Session()
        jar_session.cookies.set(
            "ttwid", "server-issued", domain="live.douyin.com", path="/"
        )
        req = requests.Request(
            "GET", "https://live.douyin.com/webcast/room/web/enter/?a=1"
        )
        prepped = jar_session.prepare_request(req)
        assert "ttwid=server-issued" in prepped.headers.get("Cookie", "")

    def test_both_channels_fail_combines_details(self):
        session = MagicMock()
        session.get.side_effect = [
            _http_resp(200, _HTML_WITHOUT_STREAM),
            _http_resp(200, ""),  # signed API: empty body (wind-control)
        ]
        info = DouyinAdapter(session).fetch("123456")
        assert info.status == LiveStreamStatus.Error
        assert "HTML备用通道" in info.detail
        assert "疑似被风控" in info.detail
        assert info.error == StreamError.EMPTY_RESPONSE

    def test_api_absent_is_authoritative(self):
        session = MagicMock()
        session.get.side_effect = [
            _http_resp(200, _HTML_WITHOUT_STREAM),
            _http_resp(200, json.dumps({"status_code": 40001, "data": {}})),
        ]
        info = DouyinAdapter(session).fetch("123456")
        assert info.status == LiveStreamStatus.Absent
        assert info.error == StreamError.ABSENT

    def test_api_not_live(self):
        session = MagicMock()
        session.get.side_effect = [
            _http_resp(200, _HTML_WITHOUT_STREAM),
            _http_resp(
                200,
                json.dumps(
                    {
                        "status_code": 0,
                        "data": {"data": [{"status": 4, "stream_url": {}}]},
                    }
                ),
            ),
        ]
        info = DouyinAdapter(session).fetch("123456")
        assert info.status == LiveStreamStatus.NotLive
        assert info.error == StreamError.NOT_LIVE

    def test_room_page_failure_still_tries_api(self):
        """Room page unreachable: best effort continues to the API."""
        session = MagicMock()
        session.get.side_effect = [
            Exception("dns failed"),
            _api_ok(_EXPECTED_FLV),
        ]
        info = DouyinAdapter(session).fetch("123456")
        assert info.status == LiveStreamStatus.Normal
        assert info.url == _EXPECTED_FLV


class TestDouyinModuleFunctions:
    def test_parse_stream_url_pull_datas(self):
        room_data = {
            "stream_url": {
                "pull_datas": {
                    "a": {
                        "stream_data": json.dumps(
                            {"data": {"origin": {"main": {"flv": "http://x/a.flv"}}}}
                        )
                    }
                }
            }
        }
        assert douyin_module.parse_stream_url(room_data) == "http://x/a.flv"

    def test_parse_stream_url_empty(self):
        assert douyin_module.parse_stream_url({}) == ""
        assert douyin_module.parse_stream_url({"stream_url": None}) == ""

    def test_extract_flv_from_html(self):
        assert douyin_module.extract_flv_from_html(_HTML_WITH_FLV) == _EXPECTED_FLV
        assert douyin_module.extract_flv_from_html("") == ""
