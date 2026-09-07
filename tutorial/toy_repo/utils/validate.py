"""输入格式校验。只做格式，不做业务。"""

import re

EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
PHONE_RE = re.compile(r"^1[3-9]\d{9}$")


def validate_email(email):
    """邮箱格式是否合法。只验格式，不验存在性。"""
    return bool(EMAIL_RE.match(email or ""))


def validate_phone(phone):
    """手机号格式是否合法。只认中国大陆 11 位。"""
    return bool(PHONE_RE.match(phone or ""))


def validate_items(items):
    """购物车条目是否合法：非空、数量为正、单价非负。"""
    if not items:
        return False
    return all(i["count"] > 0 and i["price"] >= 0 for i in items)
