# toy_repo —— 实验用的玩具代码库

一个极简电商后端，故意埋了真实项目里最烦的几种情况。

```
api/login.py            登录路由（含 validate_user）
api/order.py            下单路由
service/user_service.py UserService.login / register（也含 validate_user）
service/order_service.py OrderService.create / cancel / restock
utils/crypto.py         hash_password / verify_password
utils/validate.py       validate_email / validate_phone / validate_items
db/connection.py        get_conn / query_one / execute
db/models.py            User / Order
generated/api_client.py ← 生成代码，必须被排除
tests/test_auth.py      ← 测试，必须进索引
```

## 埋进去的四个坑

1. **同名符号**：`api/login.py` 和 `service/user_service.py` 各有一个
   `validate_user`，做的事完全不同。搜这个名字必然命中两处。
2. **跨文件调用**：`verify_password` 被 `UserService.login` 调用，"被谁调用"
   这个问题向量答不对，必须查调用关系。
3. **生成代码**：`generated/api_client.py` 内容量不小，不排除会污染检索。
4. **中文查询**：用中文问「密码怎么校验」，字符层面和 `verify_password`
   毫无重叠 —— 假向量会当场失效。

## 答案对照表

用来验证检索结果对不对：

| 问题 | 应该命中 |
|---|---|
| `verify_password` | `utils/crypto.py` |
| `validate_user` | **两处**：`api/login.py` + `service/user_service.py` |
| 密码是怎么校验的 | `utils/crypto.py` + `service/user_service.py:login` |
| 谁调用了 verify_password | `service/user_service.py` 的 `UserService.login` |
| 下单时怎么扣库存 | `service/order_service.py` 的 `create` |
| 数据库连接在哪 | `db/connection.py` |
| 手机号格式怎么校验 | `utils/validate.py` 的 `validate_phone` |
