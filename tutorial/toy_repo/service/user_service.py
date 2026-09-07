"""用户业务层：登录、注册、改密码。"""

from db.connection import query_one
from utils.crypto import hash_password, verify_password


class UserService:
    """用户相关的业务入口。所有登录逻辑最终都收敛到这里。"""

    def __init__(self, conn=None):
        self.conn = conn

    def login(self, email, password):
        """校验邮箱密码，成功返回 User，失败返回 None。

        这里刻意不抛异常 —— 上层路由自己决定是 401 还是 500。
        """
        row = query_one("SELECT * FROM users WHERE email = ?", email)
        if row is None:
            return None

        if not verify_password(password, row["password_hash"]):
            return None

        return User(**row)

    def register(self, email, password):
        """注册新用户。邮箱重复时抛异常，密码会被哈希后落库。"""
        if query_one("SELECT id FROM users WHERE email = ?", email):
            raise ValueError("email already taken")

        password_hash = hash_password(password)
        return {"email": email, "password_hash": password_hash}


def validate_user(user):
    """业务层校验：检查用户状态是否正常（封禁 / 未激活）。

    和 api/login.py 里的同名函数不是一回事。
    """
    if user is None:
        return False
    return user.status == "active"
