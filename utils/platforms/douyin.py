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
    get_cached_stream_info,
    put_cached_stream_info,
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

# 清晰度覆盖（自动降级用）：为 None 时读 config；
# live_stream_scanner 在检测到卡顿时会逐级下调（origin→uhd→hd→sd）。
_quality_override: Optional[str] = None

# 清晰度降级链：从高到低
_QUALITY_LADDER = ["origin", "uhd", "hd", "sd"]

# Bytes scanned after a "stream_url" key when extracting the stream URL
# from the (escaped) embedded JSON of the room HTML page.
_HTML_STREAM_LOOKAHEAD = 65536


def set_quality_override(quality: Optional[str]) -> None:
    """设置/清除清晰度覆盖（None=恢复 config）。"""
    global _quality_override
    _quality_override = quality


def degrade_quality() -> Optional[str]:
    """降一级清晰度，返回新的清晰度；已是最低时返回 None。"""
    from utils.config_manager import config_manager as _cm
    global _quality_override
    current = _quality_override or str(_cm.get("live_stream_quality", "origin") or "origin")
    try:
        idx = _QUALITY_LADDER.index(current)
    except ValueError:
        idx = 0
    if idx + 1 >= len(_QUALITY_LADDER):
        return None
    new_q = _QUALITY_LADDER[idx + 1]
    _quality_override = new_q
    # 清晰度变了，流地址缓存失效
    from utils.platforms.base import clear_stream_url_cache
    clear_stream_url_cache()
    return new_q


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

    # -- a_bogus 签名健康监控 ------------------------------------------
    # 签名 API 返回空响应（疑似风控/签名失效）连续失败时，自动降级：
    # 30 分钟内跳过签名通道直走 HTML，避免每次白白等 API 超时。
    # 若 HTML 也拿不到，说明可能是房间未开播而非签名问题，不计入。
    _api_consec_failures: int = 0
    _api_disabled_until: float = 0.0
    _API_FAIL_THRESHOLD = 3
    _API_DISABLE_SECONDS = 1800.0

    @classmethod
    def api_health(cls) -> dict:
        """签名通道健康状态（供诊断/UI）。"""
        import time as _time
        return {
            "consec_failures": cls._api_consec_failures,
            "disabled": _time.time() < cls._api_disabled_until,
            "disabled_remaining_s": max(
                0.0, cls._api_disabled_until - _time.time()
            ),
        }

    @classmethod
    def reset_api_health(cls) -> None:
        """重置签名健康统计（测试用）。"""
        cls._api_consec_failures = 0
        cls._api_disabled_until = 0.0

    @classmethod
    def _record_api_success(cls) -> None:
        cls._api_consec_failures = 0

    @classmethod
    def _record_api_failure(cls) -> None:
        import time as _time
        cls._api_consec_failures += 1
        if cls._api_consec_failures >= cls._API_FAIL_THRESHOLD:
            cls._api_disabled_until = _time.time() + cls._API_DISABLE_SECONDS
            logger.warning(
                "[LiveStream] a_bogus 签名通道连续 %d 次空响应，已自动降级："
                "30 分钟内直走 HTML 通道。若长期如此，可能是抖音更新了风控算法，"
                "签名需要更新。",
                cls._api_consec_failures,
            )

    @classmethod
    def _api_channel_usable(cls) -> bool:
        import time as _time
        return _time.time() >= cls._api_disabled_until

    def fetch(self, room_id: str) -> LiveStreamInfo:
        # 流地址缓存：5 分钟内同一房间直接复用，省一次 API 往返
        cached = get_cached_stream_info(self.name, room_id)
        if cached is not None:
            logger.info("[LiveStream] Douyin cache hit for room %s", room_id)
            return cached
        try:
            info = self._fetch(room_id)
        except Exception as e:
            logger.warning("[LiveStream] Douyin fetch error: %s", e)
            return self._fail(StreamError.NETWORK, "请求异常：%s" % e)
        put_cached_stream_info(self.name, room_id, info)
        return info

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
        # 签名健康检查：连续失败后自动降级，直走 HTML（此时 html 已取过，
        # 若 html 有流地址前面已返回，这里说明两通道都拿不到）
        if not self._api_channel_usable():
            logger.info(
                "[LiveStream] 签名通道降级中（剩余 %.0f 秒），跳过 API",
                self.api_health()["disabled_remaining_s"],
            )
            api_info = self._fail(
                StreamError.EMPTY_RESPONSE, "签名通道降级中，已跳过"
            )
        else:
            api_info = self._fetch_via_api(room_id, headers)
        if api_info.status == LiveStreamStatus.Normal:
            self._record_api_success()
            return api_info
        # 只有空响应（签名疑似失效）才计入健康统计；
        # 房间不存在/未开播等是正常业务状态，不怪签名。
        if api_info.error == StreamError.EMPTY_RESPONSE:
            self._record_api_failure()

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

        # Extract FLV URL (try pull_datas first, then live_core_sdk_data).
        # Quality preference is configurable (default origin = 最高画质，
        # 保检出率）；低清晰度延迟略低，tradeoff 由 review 决策。
        try:
            from utils.config_manager import config_manager
            quality = _quality_override or str(
                config_manager.get("live_stream_quality", "origin") or "origin"
            )
        except Exception:
            quality = _quality_override or "origin"
        flv_url = parse_stream_url(room_data, quality)
        if not flv_url:
            http_utils.diag_response("douyin/web_enter", r)
            return self._fail(
                StreamError.PARSE, "解析失败：接口未返回可用流地址"
            )

        return LiveStreamInfo(status=LiveStreamStatus.Normal, url=flv_url)


def parse_stream_url(room_data: dict, quality: str = "origin") -> str:
    """Extract FLV URL from Douyin room data.

    Tries every ``pull_datas`` entry first (first valid URL wins),
    then falls back to ``live_core_sdk_data``.  This dual-path approach
    is ported from MHY_Scanner's
    ``LiveDouyin::GetStreamLinkFromResponse`` and fixes a missing
    fallback in the original KuRo_Scanner.

    Args:
        quality: preferred quality (``origin``/``uhd``/``hd``/``sd``).
            Lower qualities have slightly lower latency but blurrier
            frames – default ``origin`` protects detection rate.
    """
    stream_url = room_data.get("stream_url", {})
    if not isinstance(stream_url, dict):
        return ""

    # Path 1: pull_datas (newer API)
    pull_datas = stream_url.get("pull_datas")
    if isinstance(pull_datas, dict):
        for entry in pull_datas.values():
            url = _extract_flv(entry, quality)
            if url:
                return url

    # Path 2: live_core_sdk_data (older API)
    core_sdk = stream_url.get("live_core_sdk_data", {})
    if isinstance(core_sdk, dict):
        pull_data = core_sdk.get("pull_data", {})
        url = _extract_flv(pull_data, quality)
        if url:
            return url

    return ""


# Quality fallback order: preferred -> origin -> any available.
# (Keys observed in stream_data payloads.)
_QUALITY_FALLBACK = ("origin", "uhd", "hd", "sd")


def _extract_flv(entry, quality: str = "origin") -> str:
    """Pull the FLV URL out of one stream-data entry.

    Tries *quality* first, then ``origin``, then any quality that has
    a usable ``main/flv`` URL – never worse than the old origin-only
    behaviour.
    """
    if not isinstance(entry, dict):
        return ""
    stream_data_str = entry.get("stream_data", "")
    if not isinstance(stream_data_str, str) or not stream_data_str:
        return ""
    sd = http_utils.safe_json(stream_data_str)
    if not sd:
        return ""
    data = sd.get("data")
    if not isinstance(data, dict):
        return ""
    ordered = []
    if quality:
        ordered.append(quality)
    for q in _QUALITY_FALLBACK:
        if q not in ordered:
            ordered.append(q)
    for q in ordered:
        try:
            url = data[q]["main"]["flv"] or ""
        except (KeyError, TypeError):
            continue
        if url:
            return url
    # Last resort: any quality with a main/flv URL.
    for q, qdata in data.items():
        try:
            url = qdata["main"]["flv"] or ""
        except (KeyError, TypeError, AttributeError):
            continue
        if url:
            return url
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
