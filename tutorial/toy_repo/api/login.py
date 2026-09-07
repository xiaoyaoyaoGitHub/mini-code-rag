"""登录路由。接收明文密码，校验后签发 token。"""

from service.user_service import UserService
from utils.validate import validate_email


def validate_user(payload):
    """路由层校验：只管字段齐不齐，不碰业务规则。

    注意：service 层还有一个同名函数 validate_user，做的是业务校验。
    搜这个名字会同时命中两处 —— 这正是单项目检索最烦的地方。
    """
    if "email" not in payload or "password" not in payload:
        raise ValueError("missing email or password")
    return True


def login_route(email, password):
    """处理一次登录请求，成功返回 token，失败抛异常。"""
    validate_user({"email": email, "password": password})

    if not validate_email(email):
        raise ValueError("bad email format")

    svc = UserService()
    user = svc.login(email, password)
    if user is None:
        raise PermissionError("email or password wrong")

    return issue_token(user)


def issue_token(user):
    """给用户签发一个短期有效的访问令牌。"""
    return f"token-{user.id}-{user.email}"
