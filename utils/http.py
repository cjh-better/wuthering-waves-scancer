# -*- coding: utf-8 -*-
"""
Shared HTTP helpers: session factory, defensive JSON parsing and
response diagnostics.

Consolidates logic previously duplicated across ``live_stream_scanner``
(``_safe_json``, ``_diag_response``) and ``kuro_api`` so platform
adapters share one implementation.
"""
import json
from typing import Optional

import requests
from requests.adapters import HTTPAdapter

from utils.log import get_logger


logger = get_logger("HTTP")

#: Length of the response-body preview written to the diagnostics log.
DIAG_PREVIEW_LEN = 200

#: Generic browser User-Agent used when a platform does not define its own.
DEFAULT_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/120.0.0.0 Safari/537.36"
)


def new_session(pool_connections: int = 10, pool_maxsize: int = 20) -> requests.Session:
    """Create a ``requests.Session`` with a tuned connection pool.

    Sessions must be reused (not created per request) so TCP/TLS
    connections are pooled – and so cookies (e.g. Douyin's ``ttwid``)
    persist across the calls of one logical operation.
    """
    session = requests.Session()
    adapter = HTTPAdapter(
        pool_connections=pool_connections,
        pool_maxsize=pool_maxsize,
        pool_block=False,
    )
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session


def safe_json(text: object) -> Optional[dict]:
    """Parse JSON defensively, returning *None* instead of raising.

    Equivalent to MHY_Scanner's ``json::parse(text, nullptr, false)``
    + ``is_discarded()`` check.
    """
    try:
        if not isinstance(text, str):
            return None
        return json.loads(text)
    except (ValueError, TypeError):
        return None


def diag_response(tag: str, response) -> None:
    """Log HTTP diagnostics for a platform API call.

    Records the status code, body length and a truncated preview of the
    body – exactly what a user needs to paste when reporting
    "无法获取直播流地址", so keep it compact.
    """
    try:
        body = response.text or ""
        preview = body[:DIAG_PREVIEW_LEN].replace("\n", " ").replace("\r", " ")
        logger.warning(
            "[%s] status=%s body_len=%d preview=%r",
            tag,
            response.status_code,
            len(body),
            preview,
        )
    except Exception:
        pass
