from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import BaseModel

if TYPE_CHECKING:
    from app.modules.item.model import Item


class User(BaseModel):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(
        String(255), unique=True, index=True, comment="邮箱"
    )
    is_active: Mapped[bool] = mapped_column(default=True, comment="是否激活")
    is_superuser: Mapped[bool] = mapped_column(default=False, comment="是否超管")
    full_name: Mapped[str | None] = mapped_column(
        String(255), default=None, comment="姓名"
    )
    hashed_password: Mapped[str] = mapped_column(String(128), comment="密码哈希")

    # 一对多关系:一个用户拥有多个 item。此字段不是数据库列,而是 item.owner_id 外键的 ORM 投影。
    # - back_populates="owner":与 Item.owner 配对,两端对象自动同步
    # - cascade="all, delete-orphan":删除用户时级联删除其名下 items(delete_user 依赖此机制)
    # - lazy="selectin":访问 .items 时按"本次加载到的用户主键"批量 IN 查询,避免 N+1
    items: Mapped[list[Item]] = relationship(
        back_populates="owner", cascade="all, delete-orphan", lazy="selectin"
    )
