# Item — 新接口 Copy Sample

`item` 是新增“数据库型业务接口”的最小参考样板，不承担真实产品业务。

复制为 `app/<feature>/` 后，通常只需要修改：

1. `model.py`：表字段与约束
2. `schema.py`：请求/响应结构
3. `repository.py`：数据查询
4. `service.py`：业务规则与事务
5. `api.py`：HTTP 路由

然后完成三处注册：

- `app/db/models.py` 注册 ORM Model
- `app/main.py` 注册 Router
- `alembic/versions/` 新增数据库迁移

约定：Repository 只访问数据库、不 `commit`；Service 负责业务规则与事务；API 只负责 HTTP、鉴权和依赖注入。简单业务不要额外增加 manager/usecase/runtime 层。
