"""密码哈希与校验。全局只有这两个函数碰明文密码。"""

import hashlib
import hmac
import os

SALT_BYTES = 16
ITERATIONS = 100_000


def hash_password(plain):
    """把明文密码变成可存储的哈希串。格式：salt:hash。"""
    salt = os.urandom(SALT_BYTES)
    digest = _pbkdf2(plain, salt)
    return f"{salt.hex()}:{digest.hex()}"


def verify_password(plain, stored):
    """校验明文密码是否匹配已存储的哈希串。比对用 hmac 防时序侧信道。"""
    try:
        salt_hex, digest_hex = stored.split(":")
    except ValueError:
        return False

    digest = _pbkdf2(plain, bytes.fromhex(salt_hex))
    return hmac.compare_digest(digest.hex(), digest_hex)


def _pbkdf2(plain, salt):
    """内部实现：pbkdf2-hmac-sha256。别在外面直接调。"""
    return hashlib.pbkdf2_hmac(
        "sha256", plain.encode("utf-8"), salt, ITERATIONS
    )
