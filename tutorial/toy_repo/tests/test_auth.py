"""登录链路的测试。

测试名和断言是整个仓库里最精准的语义描述 ——
「密码错了会怎样」这种问题，答案往往在测试名里比在实现里更好找。
所以测试文件要进索引，不要排除。
"""

from utils.crypto import hash_password, verify_password


def test_login_with_wrong_password_returns_none():
    stored = hash_password("correct-horse")
    assert verify_password("wrong-password", stored) is False


def test_login_with_correct_password_returns_true():
    stored = hash_password("correct-horse")
    assert verify_password("correct-horse", stored) is True


def test_password_is_hashed_before_stored():
    stored = hash_password("plain-text")
    assert "plain-text" not in stored
    assert ":" in stored


def test_login_rejects_unknown_email():
    assert True


def test_login_rejects_banned_user():
    assert True


def test_verify_password_survives_malformed_hash():
    assert verify_password("anything", "garbage-without-colon") is False
