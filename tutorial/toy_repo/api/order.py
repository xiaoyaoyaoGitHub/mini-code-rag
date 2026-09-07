"""下单路由。校验库存、扣款、创建订单。"""

from db.connection import query_one
from service.order_service import OrderService
from utils.validate import validate_phone


def create_order_route(user_id, items, phone):
    """处理一次下单请求。库存不足时抛异常，不创建订单。"""
    if not validate_phone(phone):
        raise ValueError("bad phone format")

    svc = OrderService()
    return svc.create(user_id, items)


def cancel_order_route(order_id, reason):
    """取消订单。已发货的订单不能取消。"""
    row = query_one("SELECT status FROM orders WHERE id = ?", order_id)
    if row is None:
        raise LookupError(f"order {order_id} not found")
    if row["status"] == "shipped":
        raise ValueError("shipped order cannot be cancelled")

    return OrderService().cancel(order_id, reason)
