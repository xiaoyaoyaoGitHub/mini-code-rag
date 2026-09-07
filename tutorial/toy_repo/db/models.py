"""数据模型。纯数据结构，不放业务逻辑。"""

from dataclasses import dataclass, field


@dataclass
class User:
    """用户表映射。password_hash 永远不要出现在对外响应里。"""

    id: int
    email: str
    password_hash: str = ""
    status: str = "active"
    created_at: str = ""


@dataclass
class Order:
    """订单表映射。items 是反范式存的 JSON。"""

    id: int
    user_id: int
    total: float = 0.0
    status: str = "created"
    items: list = field(default_factory=list)
