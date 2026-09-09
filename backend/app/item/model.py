import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class Item(BaseModel):
    """数据库型业务模块的最小示例模型。"""

    __tablename__ = "item"

    title: Mapped[str] = mapped_column(String(255), comment="标题")
    description: Mapped[str | None] = mapped_column(
        String(255), default=None, comment="描述"
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        index=True,
        comment="所属用户ID",
    )
