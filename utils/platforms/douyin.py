# -*- coding: utf-8 -*-
"""
Douyin live-stream adapter.

Lookup flow (verified end-to-end 2026-10-06):

1. ``GET https://live.douyin.com/<room_id>`` – the server issues the
   ``ttwid`` cookie via ``Set-Cookie`` (self-generated values are
   rejected, it *must* come from the server) and the page embeds the
   room JSON.  The shared session carries the cookie automatically.
2. Extract the stream URL from the page's embedded JSON (fast, no
   signing overhead).
3. Fall back to the signed ``web/enter`` JSON API: the url-encoded
   query string is signed with ``a_bogus`` (see ``utils.abogus``) using
   the *same* User-Agent as the request headers, then appended as
   ``&a_bogus=<sig>``.  Unsigned requests get HTTP 200 with an empty
   body (suspected wind-control).
4. If both channels fail, return the combined reasons.

No signature reverse-engineering is done here – ``utils.abogus`` is a
vendored public implementation.  If Douyin upgrades wind-control and
signatures stop working, channel 2 (HTML extraction) keeps working
independently; the code degrades gracefully instead of breaking.
"""
import re
import urllib.parse
from typing import Optional

from utils import http as http_utils
from utils.abogus import ab_sign
from utils.log import get_logger
from utils.platforms.base import (
    LiveStreamInfo,
    LiveStreamStatus,
    PlatformAdapter,
    StreamError,
)


logger = get_logger("LiveStream")

# NOTE: the UA below is used for request headers *and* for signing –
# they must be identical, the signature covers the UA string.
_DOUYIN_UA = (
    "Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/116.0.5845.97 Safari/537.36 "
    "Core/1.116.567.400 QQBrowser/19.7.6764.400"
)
_DOUYIN_ROOM_PAGE_URL = "https://live.douyin.com/%s"
_DOUYIN_API_URL = "https://live.douyin.com/webcast/room/web/enter/"
_API_TIMEOUT = 10
_HTML_TIMEOUT = 10

# Bytes scanned after a "stream_url" key when extracting the stream URL
# from the (escaped) embedded JSON of the room HTML page.
_HTML_STREAM_LOOKAHEAD = 65536


def _api_params(room_id: str) -> dict:
    """Query params for ``web/enter``.

    Key set and UA must stay in sync with what was verified
    end-to-end: ``msToken`` is empty but *must* be present.
    """
    return {
        "aid": "6383",
        "app_name": "douyin_web",
        "live_id": "1",
        "device_platform": "web",
        "language": "zh-CN",
        "browser_language": "zh-CN",
        "browser_platform": "Win32",
        "browser_name": "Chrome",
        "browser_version": "116.0.0.0",
        "web_rid": room_id,
        "msToken": "",
    }


def _signed_api_url(room_id: str) -> str:
    """Build the signed ``web/enter`` URL for *room_id*.

    Signs the url-encoded query string (``ab_sign``) and appends the
    signature as ``a_bogus``.  Falls back to the unsigned URL if
    signing itself fails – best effort, never worse than before.
    """
    query = urllib.parse.urlencode(_api_params(room_id))
    try:
        sig = ab_sign(query, _DOUYIN_UA)
    except Exception as e:
        logger.warning("[LiveStream] a_bogus signing failed, trying unsigned: %s", e)
        return "%s?%s" % (_DOUYIN_API_URL, query)
    return "%s?%s&a_bogus=%s" % (
        _DOUYIN_API_URL,
        query,
        urllib.parse.quote(sig, safe=""),
    )


class DouyinAdapter(PlatformAdapter):
    """Douyin live-stream URL resolver (HTML-first, signed API second)."""

    name = "douyin"

    def fetch(self, room_id: str) -> LiveStreamInfo:
        try:
            return self._fetch(room_id)
        except Exception as e:
            logger.warning("[LiveStream] Douyin fetch error: %s", e)
            return self._fail(StreamError.NETWORK, "请求异常：%s" % e)

    def _fetch(self, room_id: str) -> LiveStreamInfo:
        headers = {
            "User-Agent": _DOUYIN_UA,
            "Referer": _DOUYIN_ROOM_PAGE_URL % room_id,
        }

        # Channel 1 – room HTML page.  Serves two purposes: the server
        # issues the ``ttwid`` cookie (picked up by the shared session)
        # and the page embeds the room JSON we can extract directly.
        html: Optional[str] = None
        try:
            r = self._session.get(
                _DOUYIN_ROOM_PAGE_URL % room_id,
                headers={"User-Agent": _DOUYIN_UA},
                timeout=_HTML_TIMEOUT,
            )
            if r.status_code == 200:
                html = r.text or ""
            else:
                http_utils.diag_response("douyin/room_page", r)
                logger.warning(
                    "[LiveStream] Douyin room page HTTP %s", r.status_code
                )
        except Exception as e:
            logger.warning("[LiveStream] Douyin room page fetch failed: %s", e)

        html_detail = ""
        if html and html.strip():
            flv_url = extract_flv_from_html(html)
            if flv_url:
                return LiveStreamInfo(
                    status=LiveStreamStatus.Normal,
                    url=flv_url,
                    detail="经由HTML备用通道获取",
                )
            html_detail = "页面未包含直播流地址(房间可能未开播，或页面结构已变化)"
        elif html is not None:
            html_detail = "页面返回空内容"
        else:
            html_detail = "页面加载失败"

        # Channel 2 – signed web/enter JSON API.
        api_info = self._fetch_via_api(room_id, headers)
        if api_info.status == LiveStreamStatus.Normal:
            return api_info

        # Neither channel worked – combine both reasons for the user.
        combined = "HTML备用通道：%s" % html_detail
        if api_info.detail:
            combined = "%s；签名API：%s" % (combined, api_info.detail)
        return LiveStreamInfo(
            status=api_info.status,
            detail=combined,
            error=api_info.error,
        )

    def _fetch_via_api(self, room_id: str, headers: dict) -> LiveStreamInfo:
        """Query the signed ``web/enter`` JSON API."""
        url = _signed_api_url(room_id)
        try:
            r = self._session.get(url, headers=headers, timeout=_API_TIMEOUT)
        except Exception as e:
            return self._fail(StreamError.NETWORK, "网络请求异常：%s" % e)

        if r.status_code != 200:
            http_utils.diag_response("douyin/web_enter", r)
            return self._fail(
                StreamError.HTTP_ERROR,
                "网络请求失败(HTTP %s)" % r.status_code,
            )

        body = r.text or ""
        if not body.strip():
            http_utils.diag_response("douyin/web_enter", r)
            return self._fail(
                StreamError.EMPTY_RESPONSE, "接口返回空响应(疑似被风控)"
            )

        info = http_utils.safe_json(body)
        if info is None:
            http_utils.diag_response("douyin/web_enter", r)
            return self._fail(StreamError.EMPTY_RESPONSE, "接口返回非法JSON")

        if info.get("status_code") != 0:
            return self._fail(
                StreamError.ABSENT,
                "房间不存在(接口 status_code=%s)" % info.get("status_code"),
                status=LiveStreamStatus.Absent,
            )

        data_arr = info.get("data", {}).get("data", [])
        if not data_arr:
            return self._fail(
                StreamError.ABSENT,
                "房间不存在(接口无房间数据)",
                status=LiveStreamStatus.Absent,
            )

        room_data = data_arr[0]
        status = room_data.get("status")
        if status == 4:
            return self._fail(
                StreamError.NOT_LIVE, "主播未开播",
                status=LiveStreamStatus.NotLive,
            )
        if status != 2:
            return self._fail(
                StreamError.UNKNOWN, "未知的房间状态(status=%s)" % status
            )

        # Extract FLV URL (try pull_datas first, then live_core_sdk_data)
        flv_url = parse_stream_url(room_data)
        if not flv_url:
            http_utils.diag_response("douyin/web_enter", r)
            return self._fail(
                StreamError.PARSE, "解析失败：接口未返回可用流地址"
            )

        return LiveStreamInfo(status=LiveStreamStatus.Normal, url=flv_url)


def parse_stream_url(room_data: dict) -> str:
    """Extract FLV URL from Douyin room data.

    Tries every ``pull_datas`` entry first (first valid URL wins),
    then falls back to ``live_core_sdk_data``.  This dual-path approach
    is ported from MHY_Scanner's
    ``LiveDouyin::GetStreamLinkFromResponse`` and fixes a missing
    fallback in the original KuRo_Scanner.
    """
    stream_url = room_data.get("stream_url", {})
    if not isinstance(stream_url, dict):
        return ""

    # Path 1: pull_datas (newer API)
    pull_datas = stream_url.get("pull_datas")
    if isinstance(pull_datas, dict):
        for entry in pull_datas.values():
            url = _extract_flv(entry)
            if url:
                return url

    # Path 2: live_core_sdk_data (older API)
    core_sdk = stream_url.get("live_core_sdk_data", {})
    if isinstance(core_sdk, dict):
        pull_data = core_sdk.get("pull_data", {})
        url = _extract_flv(pull_data)
        if url:
            return url

    return ""


def _extract_flv(entry) -> str:
    """Pull the ``origin/main/flv`` URL out of one stream-data entry."""
    if not isinstance(entry, dict):
        return ""
    stream_data_str = entry.get("stream_data", "")
    if not isinstance(stream_data_str, str) or not stream_data_str:
        return ""
    sd = http_utils.safe_json(stream_data_str)
    if not sd:
        return ""
    try:
        return sd["data"]["origin"]["main"]["flv"] or ""
    except (KeyError, TypeError):
        return ""


def extract_flv_from_html(html: str) -> str:
    """Extract a playable stream URL from a Douyin room HTML page.

    The room JSON is embedded with escaped quotes (``\\"`` and
    sometimes ``\\\\"``), so both the key lookup and the URL capture
    tolerate stray backslashes.  The search is scoped to the text
    following a ``stream_url`` key to avoid picking up unrelated media
    URLs elsewhere on the page.  Prefers FLV (same as the API path),
    falls back to HLS, then to any ``.flv`` URL on the page.
    """
    if not html:
        return ""
    key_pat = re.compile(r'(?:\\)*"stream_url')
    url_pat = re.compile(
        r'(?:\\)*"(flv|hls)(?:\\)*"\s*:(?:\\)*"(https?://[^"\\<>\s]+)'
    )
    hls_url = ""
    for m in key_pat.finditer(html):
        window = html[m.end(): m.end() + _HTML_STREAM_LOOKAHEAD]
        for um in url_pat.finditer(window):
            url = um.group(2)
            if not url.startswith("http"):
                continue
            if um.group(1) == "flv":
                return url
            if not hls_url:
                hls_url = url
    if hls_url:
        return hls_url
    # Last resort: any .flv URL on the page (structure may have changed).
    loose = re.search(r'https?://[^"\\<>\s]+\.flv[^"\\<>\s]*', html)
    if loose:
        logger.warning(
            "[LiveStream] HTML extraction fell back to loose .flv match"
        )
        return loose.group(0)
    return ""
