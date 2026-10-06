# -*- coding: utf-8 -*-
"""
Live-stream platform adapters.

Each platform (Bilibili, Douyin) gets an adapter that resolves a room
ID to a playable stream URL.  ``LiveStreamScanner`` only keeps the
capture → queue → decode pipeline and dispatches URL resolution here.
"""
from utils.platforms.base import (
    LiveStreamInfo,
    LiveStreamStatus,
    PlatformAdapter,
    StreamError,
)
from utils.platforms.bilibili import BilibiliAdapter, parse_play_info
from utils.platforms.douyin import (
    DouyinAdapter,
    extract_flv_from_html,
    parse_stream_url,
)


_ADAPTERS = {
    "bilibili": BilibiliAdapter,
    "douyin": DouyinAdapter,
}


def get_adapter(platform: str, session):
    """Return the adapter for *platform*, or *None* if unknown."""
    cls = _ADAPTERS.get(platform)
    return cls(session) if cls is not None else None


__all__ = [
    "LiveStreamInfo",
    "LiveStreamStatus",
    "PlatformAdapter",
    "StreamError",
    "BilibiliAdapter",
    "DouyinAdapter",
    "get_adapter",
    "parse_play_info",
    "parse_stream_url",
    "extract_flv_from_html",
]
