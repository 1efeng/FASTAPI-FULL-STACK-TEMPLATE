"""集中注册所有 SQLAlchemy 表模型。

所有独立入口（Alembic、初始化脚本、应用启动、测试）统一导入本模块。
新增业务模型时只需在这里注册一次。
"""

from app.user.model import User  # noqa: F401
