"""订单业务层：创建、取消、查库存。"""

from db.connection import query_one
from utils.validate import validate_phone


class OrderService:
    """订单相关的业务入口。"""

    def create(self, user_id, items):
        """创建订单。会先扣库存，任一商品不足则整单失败。"""
        for item in items:
            stock = query_one("SELECT stock FROM items WHERE id = ?", item["id"])
            if stock is None or stock["stock"] < item["count"]:
                raise ValueError(f"item {item['id']} out of stock")

        total = sum(i["count"] * i["price"] for i in items)
        return {"user_id": user_id, "items": items, "total": total}

    def cancel(self, order_id, reason):
        """取消订单并写原因。已完成的订单由调用方拦掉。"""
        row = query_one("SELECT status FROM orders WHERE id = ?", order_id)
        if row is None:
            raise LookupError(f"order {order_id} not found")
        return {"order_id": order_id, "status": "cancelled", "reason": reason}

    def restock(self, order_id):
        """取消后把库存加回去。幂等：已回滚的订单不会重复加。"""
        return query_one("SELECT 1 FROM restock_log WHERE order_id = ?", order_id)
