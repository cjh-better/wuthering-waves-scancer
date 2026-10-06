# -*- coding: utf-8 -*-
"""
Bilibili live-stream adapter.

``room_init`` resolves the real room ID + live status, then
``getRoomPlayInfo`` (v2) yields the stream URL.  HTTP errors and
malformed JSON are handled defensively (ported from MHY_Scanner
``LiveBili::GetLiveStreamInfo``).
"""
from typing import Optional

from utils import http as http_utils
from utils.log import get_logger
from utils.platforms.base import (
    LiveStreamInfo,
    LiveStreamStatus,
    PlatformAdapter,
    StreamError,
)


logger = get_logger("LiveStream")

_BILIBILI_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/110.0.0.0 Safari/537.36 Edg/110.0.1587.41"
)
_BILIBILI_HEADERS = {
    "User-Agent": _BILIBILI_UA,
    "Referer": "https://live.bilibili.com",
}
_ROOM_INIT_URL = "https://api.live.bilibili.com/room/v1/Room/room_init"
_PLAY_INFO_URL = (
    "https://api.live.bilibili.com/xlive/web-room/v2/index/getRoomPlayInfo"
)
_API_TIMEOUT = 5


class BilibiliAdapter(PlatformAdapter):
    """Bilibili live-stream URL resolver."""

    name = "bilibili"

    def fetch(self, room_id: str) -> LiveStreamInfo:
        try:
            return self._fetch(room_id)
        except Exception as e:
            logger.warning("[LiveStream] Bilibili fetch error: %s", e)
            return self._fail(
                StreamError.NETWORK, "请求异常：%s" % e
            )

    def _fetch(self, room_id: str) -> LiveStreamInfo:
        # Step 1 – room_init (get real room ID + live status)
        r, exc = self._get(
            "room_init", _ROOM_INIT_URL, params={"id": room_id},
            timeout=_API_TIMEOUT,
        )
        if r is None:
            return self._fail(StreamError.NETWORK, "网络请求异常：%s" % exc)
        if r.status_code != 200:
            return self._fail(
                StreamError.HTTP_ERROR,
                "网络请求失败(HTTP %s)" % r.status_code,
            )

        room_info = http_utils.safe_json(r.text)
        if room_info is None:
            http_utils.diag_response("bilibili/room_init", r)
            return self._fail(
                StreamError.EMPTY_RESPONSE, "接口返回空响应或非法JSON"
            )

        code = room_info.get("code")
        if code == 60004:
            return self._fail(
                StreamError.ABSENT, "房间不存在",
                status=LiveStreamStatus.Absent,
            )
        if code != 0:
            http_utils.diag_response("bilibili/room_init", r)
            return self._fail(
                StreamError.UNKNOWN, "接口报错(code=%s)" % code
            )

        data = room_info.get("data") or {}
        if data.get("live_status") != 1:
            return self._fail(
                StreamError.NOT_LIVE, "主播未开播",
                status=LiveStreamStatus.NotLive,
            )
        real_room_id = data.get("room_id")

        # Step 2 – getRoomPlayInfo (v2)
        params = {
            "room_id": real_room_id,
            "protocol": "0,1",
            "format": "0,2",
            "codec": "0",
            "only_audio": "0",
            "only_video": "0",
            "qn": "10000",
        }
        r, exc = self._get(
            "play_info", _PLAY_INFO_URL, params=params, timeout=_API_TIMEOUT
        )
        if r is None:
            return self._fail(StreamError.NETWORK, "网络请求异常：%s" % exc)
        if r.status_code != 200:
            return self._fail(
                StreamError.HTTP_ERROR,
                "网络请求失败(HTTP %s)" % r.status_code,
            )

        play_info = http_utils.safe_json(r.text)
        if play_info is None:
            http_utils.diag_response("bilibili/play_info", r)
            return self._fail(
                StreamError.EMPTY_RESPONSE, "接口返回空响应或非法JSON"
            )

        stream_url = parse_play_info(play_info)
        if not stream_url:
            http_utils.diag_response("bilibili/play_info", r)
            return self._fail(
                StreamError.PARSE, "解析失败：未找到可用流地址"
            )

        return LiveStreamInfo(
            status=LiveStreamStatus.Normal,
            url=stream_url,
            headers=dict(_BILIBILI_HEADERS),
        )


def parse_play_info(play_info: dict) -> str:
    """Extract the first usable stream URL from ``getRoomPlayInfo``.

    Walks all streams/formats/codecs/url_infos and returns the first
    complete URL.  In the common case this is identical to the old
    "first entry" behaviour, but it no longer fails when the first
    entry is missing a host or token.
    """
    try:
        streams = play_info["data"]["playurl_info"]["playurl"]["stream"]
    except (KeyError, TypeError):
        return ""
    if not isinstance(streams, list):
        return ""
    for stream in streams:
        if not isinstance(stream, dict):
            continue
        for fmt in stream.get("format", []) or []:
            if not isinstance(fmt, dict):
                continue
            for codec in fmt.get("codec", []) or []:
                if not isinstance(codec, dict):
                    continue
                base_url = codec.get("base_url", "")
                for url_info in codec.get("url_info", []) or []:
                    if not isinstance(url_info, dict):
                        continue
                    host = url_info.get("host", "")
                    extra = url_info.get("extra", "")
                    if host and base_url:
                        url = "%s%s%s" % (host, base_url, extra)
                        if url.startswith("http"):
                            return url
    return ""
