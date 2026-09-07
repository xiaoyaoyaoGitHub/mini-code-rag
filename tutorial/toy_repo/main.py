"""应用入口：装配 service 层并启动 HTTP 服务。"""

from api.login import login_route
from api.order import create_order_route
from db.connection import get_conn


def build_app():
    """把所有路由注册进来，返回可运行的应用对象。"""
    routes = {
        "POST /login": login_route,
        "POST /orders": create_order_route,
    }
    conn = get_conn()
    return {"routes": routes, "conn": conn}


def main():
    app = build_app()
    for path, handler in app["routes"].items():
        print(f"{path} -> {handler.__name__}")


if __name__ == "__main__":
    main()
