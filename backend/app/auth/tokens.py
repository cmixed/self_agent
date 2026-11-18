"""令牌与验证码生成。

- 登录令牌：随机 32 字节，URL 安全字符；**只存散列**，库泄露也无法直接冒用。
- 重置验证码：6 位数字；同样只存散列，且限制尝试次数与有效期。
"""

from __future__ import annotations

import hashlib
import secrets

TOKEN_BYTES = 32
RESET_CODE_DIGITS = 6


def new_token() -> str:
    """生成明文令牌（仅在登录响应中出现一次）。"""
    return secrets.token_urlsafe(TOKEN_BYTES)


def token_digest(token: str) -> str:
    """令牌落库前的摘要（sha256 十六进制）。"""
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_reset_code() -> str:
    """生成 6 位数字验证码（前导零保留）。"""
    return f"{secrets.randbelow(10**RESET_CODE_DIGITS):0{RESET_CODE_DIGITS}d}"


def reset_code_digest(user_id: str, code: str) -> str:
    """验证码摘要绑定 user_id，避免同一验证码跨账号复用。"""
    return hashlib.sha256(f"{user_id}:{code}".encode()).hexdigest()
