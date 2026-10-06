# -*- coding: utf-8 -*-
"""Token 有效性判定：纯函数，可单元测试。

约定（库街区 API）：
- code == 220 → token 明确过期
- code == 200 → token 有效
- code == -1  → 本地网络失败，**不得**判定为过期（避免误删/误标）
- 其他 code   → 未知
"""
from typing import Any, Dict, Tuple

TOKEN_EXPIRED_CODE = 220
TOKEN_OK_CODE = 200
NETWORK_ERROR_CODE = -1


def is_token_expired_code(code: Any) -> bool:
    """该 code 是否明确表示 token 已过期。"""
    return code == TOKEN_EXPIRED_CODE


def classify_token_check_response(resp: Dict[str, Any]) -> Tuple[str, str]:
    """把一次有效性检查的响应分类为 (状态, 说明)。

    状态 ∈ {"可用", "过期", "未知"}。
    """
    code = resp.get("code")
    if is_token_expired_code(code):
        return "过期", "Token已过期，右键可一键重新获取"
    if code == NETWORK_ERROR_CODE:
        return "未知", resp.get("msg", "网络检查失败") or "网络检查失败"
    if code == TOKEN_OK_CODE:
        return "可用", ""
    return "未知", resp.get("msg", "接口未返回明确状态") or "接口未返回明确状态"
