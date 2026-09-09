"""集中注册所有 SQLAlchemy 表模型。

SQLAlchemy 在第一次触发 mapper 配置(第一条查询/迁移)之前,必须先把所有模型类
import 进 Base 的 registry,否则 relationship 中按字符串引用的类名(如
User.items 引用 'Item')会解析失败,报 InvalidRequestError。

所有独立入口(alembic 迁移、initial_data、应用启动、测试)统一 import 本模块,
新增模型只需在下方加一行,各处入口无需改动。
"""

from app.item.model import Item  # noqa: F401
from app.user.model import User  # noqa: F401
