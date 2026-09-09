import uuid

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import BaseModel


class Demo(BaseModel):
    """数据库型业务接口的可复制 CRUD 示例。"""

    __tablename__ = "demo"

    title: Mapped[str] = mapped_column(String(255), comment="标题")
    description: Mapped[str | None] = mapped_column(
        String(255), default=None, comment="描述"
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"),
        index=True,
        comment="所属用户ID",
    )
