# -*- coding: utf-8 -*-
"""分享链接 → 房间 ID 解析（含短链跳转）。

用户手里通常是分享链接而不是纯数字房间号——尤其是抖音 App
分享出来的 ``v.douyin.com/xxxx`` 短链，里面根本没有数字房间号，
必须跟随 HTTP 跳转才能拿到真实地址。本模块把"粘贴任意分享内容"
统一收敛为房间 ID：

1. 纯数字 → 直接返回；
2. 完整直播间 URL（``live.douyin.com`` / ``live.bilibili.com``）→ 正则提取；
3. 短链（``v.douyin.com``、``b23.tv``）→ HTTP 跟随跳转 → 对最终 URL
   重新走第 2 步；
4. 都失败 → 返回 ``""``，由调用方提示用户。

其中第 3 步需要网络，由调用方显式调用 :func:`resolve_room_id`；
:func:`extract_room_id` 是纯函数，不做任何网络请求。
"""

import re
from typing import Optional
from urllib.parse import urlparse

from utils.http import new_session
from utils.log import get_logger


logger = get_logger("RoomURL")


#: 需要跟随跳转解析的短链域名
_SHORT_LINK_HOSTS = ("v.douyin.com", "b23.tv")

#: 输入文本里捞 URL（分享文案常混着中文）
_URL_RE = re.compile(r"https?://[^\s\"'<>]+", re.IGNORECASE)

#: 各平台房间号模式（按优先级排序）
_DOYIN_PATTERNS = (
    re.compile(r"live\.douyin\.com/(\d{4,})", re.IGNORECASE),
    re.compile(r"[?&]room_id=(\d{4,})", re.IGNORECASE),
)
_BILIBILI_PATTERNS = (
    re.compile(r"live\.bilibili\.com/(\d{4,})", re.IGNORECASE),
    re.compile(r"[?&]room_id=(\d{4,})", re.IGNORECASE),
)


def _patterns_for(platform: str):
    if platform == "douyin":
        return _DOYIN_PATTERNS
    if platform == "bilibili":
        return _BILIBILI_PATTERNS
    return ()


def extract_room_id(text: str, platform: str) -> str:
    """从输入文本中提取房间 ID（纯函数，不做网络请求）。

    短链（如 ``v.douyin.com/xxxx``）无法直接提取，返回 ``""``；
    调用方应先用 :func:`find_short_link` 判断，再走
    :func:`resolve_room_id` 做跳转解析。
    """
    if not text:
        return ""
    text = text.strip()
    if text.isdigit() and len(text) >= 4:
        return text
    # 分享文案里可能混着链接，先把 URL 捞出来优先匹配
    haystacks = [text]
    url_match = _URL_RE.search(text)
    if url_match:
        haystacks.insert(0, url_match.group(0))
    for haystack in haystacks:
        for pattern in _patterns_for(platform):
            found = pattern.search(haystack)
            if found:
                return found.group(1)
    # 跨平台兜底：任意连续 4 位以上数字（保持历史行为）
    fallback = re.search(r"\d{4,}", text)
    return fallback.group(0) if fallback else ""


def find_short_link(text: str) -> Optional[str]:
    """输入中是否包含需要跳转解析的短链；返回短链 URL，不存在返回 None。"""
    if not text:
        return None
    url_match = _URL_RE.search(text)
    if not url_match:
        return None
    url = url_match.group(0).rstrip(".,;!?")
    try:
        host = urlparse(url).netloc.lower()
    except Exception:
        return None
    if any(host == short or host.endswith("." + short) for short in _SHORT_LINK_HOSTS):
        return url
    return None


def resolve_room_id(short_url: str, platform: str, timeout: float = 8.0) -> str:
    """跟随短链跳转并解析出房间 ID。

    失败返回 ``""``（不抛异常），调用方按普通"无法识别"处理。
    """
    try:
        final_url = _follow_redirects(short_url, timeout)
        if not final_url:
            logger.warning("[RoomURL] 短链跳转失败: %s", short_url)
            return ""
        room_id = extract_room_id(final_url, platform)
        if room_id:
            logger.info("[RoomURL] 短链解析成功: %s -> 房间 %s", short_url, room_id)
        else:
            logger.warning("[RoomURL] 跳转后未找到房间号: %s", final_url)
        return room_id
    except Exception as e:
        logger.warning("[RoomURL] 短链解析异常 %s: %s", short_url, e)
        return ""


def _follow_redirects(url: str, timeout: float) -> str:
    """跟随跳转返回最终 URL；失败返回 ""。

    先试 HEAD（轻量），部分站点不支持 HEAD 时回退 GET（stream 模式，
    拿到响应头即关闭，不下载 body）。

    两次尝试平分 *timeout* 预算，保证总量有界（调用方的 closeEvent
    等待依赖这个上界）。
    """
    session = new_session()
    attempt_timeout = timeout / 2
    try:
        try:
            response = session.head(url, allow_redirects=True, timeout=attempt_timeout)
            if response.url and response.url != url:
                return response.url
        except Exception:
            pass
        try:
            response = session.get(url, allow_redirects=True, timeout=attempt_timeout, stream=True)
            try:
                return response.url or ""
            finally:
                response.close()
        except Exception:
            return ""
    finally:
        session.close()
