# -*- coding: utf-8 -*-
"""
Platform-adapter base types for live-stream URL resolution.

``LiveStreamStatus`` is the coarse outcome (mirrors MHY_Scanner);
``StreamError`` is the fine-grained machine-readable reason attached
whenever the status is ``Error`` (or ``Absent``/``NotLive``).  The UI
keeps showing the human-readable ``detail`` string – the enum exists so
callers (and tests) can classify failures without substring matching.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import IntEnum
from typing import Dict, Optional

import requests


# -- stream URL cache ---------------------------------------------------
# 同一房间短时间内重复查询直接命中缓存，省一次 API 往返。
# 只缓存成功的 Normal 结果；TTL 5 分钟（流地址有时效，太长会失效）。
class LiveStreamStatus(IntEnum):
    """Live stream status codes (mirrors MHY_Scanner LiveStreamStatus)."""
    Normal = 0
    Absent = 1
    NotLive = 2
    Error = 3


class StreamError(IntEnum):
    """Fine-grained failure reason for a stream-info lookup."""

    NONE = 0          # no error (status is Normal/Absent/NotLive)
    NETWORK = 1       # request raised (timeout, DNS, connection …)
    HTTP_ERROR = 2    # non-200 HTTP status
    EMPTY_RESPONSE = 3  # HTTP 200 with empty/invalid body (suspected wind-control)
    ABSENT = 4        # room does not exist
    NOT_LIVE = 5      # streamer is offline
    PARSE = 6         # response parsed but no usable stream URL found
    UNKNOWN = 7       # anything else

    @classmethod
    def describe(cls, error: "StreamError", extra: str = "") -> str:
        """Default human-readable text for an error (UI may refine)."""
        base = {
            cls.NONE: "",
            cls.NETWORK: "网络请求异常",
            cls.HTTP_ERROR: "网络请求失败",
            cls.EMPTY_RESPONSE: "接口返回空响应(疑似被风控)",
            cls.ABSENT: "房间不存在",
            cls.NOT_LIVE: "主播未开播",
            cls.PARSE: "解析失败：未找到可用流地址",
            cls.UNKNOWN: "未知错误",
        }.get(error, "未知错误")
        return "%s%s" % (base, extra)


@dataclass
class LiveStreamInfo:
    """Bundled result of a live stream query (status + url + headers).

    Ported from MHY_Scanner's ``LiveStreamInfo`` struct so that callers
    get status and URL in a single call instead of two separate methods.
    """
    status: LiveStreamStatus
    url: str = ""
    headers: Dict[str, str] = field(default_factory=dict)
    detail: str = ""  # human-readable failure reason, shown to the user
    error: StreamError = StreamError.NONE  # machine-readable reason


_STREAM_URL_CACHE: Dict[tuple, tuple] = {}  # (platform, room_id) -> (LiveStreamInfo, timestamp)
_STREAM_URL_CACHE_TTL = 300.0
_STREAM_URL_CACHE_MAX = 64


def get_cached_stream_info(platform: str, room_id: str) -> Optional[LiveStreamInfo]:
    """命中则返回缓存的 LiveStreamInfo，否则 None。"""
    import time as _time
    key = (platform, room_id)
    entry = _STREAM_URL_CACHE.get(key)
    if entry is None:
        return None
    info, ts = entry
    if _time.time() - ts > _STREAM_URL_CACHE_TTL:
        _STREAM_URL_CACHE.pop(key, None)
        return None
    return info


def put_cached_stream_info(platform: str, room_id: str, info: LiveStreamInfo) -> None:
    """只缓存 Normal 结果。"""
    import time as _time
    if info.status != LiveStreamStatus.Normal or not info.url:
        return
    if len(_STREAM_URL_CACHE) >= _STREAM_URL_CACHE_MAX:
        # 淘汰最旧的一条
        oldest = min(_STREAM_URL_CACHE.items(), key=lambda kv: kv[1][1])[0]
        _STREAM_URL_CACHE.pop(oldest, None)
    _STREAM_URL_CACHE[(platform, room_id)] = (info, _time.time())


def clear_stream_url_cache() -> None:
    """清空流地址缓存（清晰度切换/手动刷新时调用）。"""
    _STREAM_URL_CACHE.clear()




class PlatformAdapter(ABC):
    """Resolves a room ID to a playable stream URL for one platform.

    Adapters share the caller's ``requests.Session`` so cookies (e.g.
    Douyin's ``ttwid``) persist across the calls of one lookup and
    TCP/TLS connections are pooled.
    """

    #: Short platform key used for logging (``"bilibili"``/``"douyin"``).
    name: str = "unknown"

    def __init__(self, session: requests.Session):
        self._session = session

    @abstractmethod
    def fetch(self, room_id: str) -> LiveStreamInfo:
        """Resolve *room_id* to a :class:`LiveStreamInfo`."""
        raise NotImplementedError

    # -- shared helpers -------------------------------------------------

    def _get(self, tag: str, url: str, **kwargs):
        """GET with diagnostics logging on non-200 responses.

        Returns the response, or *None* when the request itself raised.
        ``tag`` is forwarded to the diagnostics log.
        """
        from utils import http as http_utils

        try:
            response = self._session.get(url, **kwargs)
        except Exception as exc:
            return None, exc
        if response.status_code != 200:
            http_utils.diag_response("%s/%s" % (self.name, tag), response)
        return response, None

    @staticmethod
    def _fail(error: StreamError, detail: str = "",
              status: LiveStreamStatus = LiveStreamStatus.Error) -> LiveStreamInfo:
        """Build a failed :class:`LiveStreamInfo` with enum + text."""
        return LiveStreamInfo(
            status=status,
            detail=detail or StreamError.describe(error),
            error=error,
        )
