"""口令散列：PBKDF2-HMAC-SHA256（标准库实现，不引入新依赖）。

存储格式：``pbkdf2_sha256$<迭代次数>$<salt_hex>$<hash_hex>``。
校验使用 ``hmac.compare_digest``，避免比较耗时泄露信息。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

ALGORITHM = "pbkdf2_sha256"
ITERATIONS = 200_000
SALT_BYTES = 16
MIN_PASSWORD_LENGTH = 8


class PasswordError(ValueError):
    """口令不满足策略。"""


def hash_password(password: str, *, iterations: int = ITERATIONS) -> str:
    """生成口令散列；每次调用使用新的随机盐。"""
    if len(password) < MIN_PASSWORD_LENGTH:
        raise PasswordError(f"密码至少 {MIN_PASSWORD_LENGTH} 位")
    salt = secrets.token_bytes(SALT_BYTES)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return f"{ALGORITHM}${iterations}${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    """校验口令；``stored`` 为空或格式损坏时返回 False（不抛异常）。"""
    if not stored:
        return False
    try:
        algorithm, raw_iterations, salt_hex, digest_hex = stored.split("$", 3)
        if algorithm != ALGORITHM:
            return False
        iterations = int(raw_iterations)
        salt = bytes.fromhex(salt_hex)
        expected = bytes.fromhex(digest_hex)
    except ValueError, AttributeError:
        return False
    actual = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(actual, expected)


def needs_rehash(stored: str | None, *, iterations: int = ITERATIONS) -> bool:
    """旧散列的迭代次数低于当前策略时，登录成功后应静默升级。"""
    if not stored:
        return False
    try:
        _, raw_iterations, _, _ = stored.split("$", 3)
        return int(raw_iterations) < iterations
    except ValueError, AttributeError:
        return True
