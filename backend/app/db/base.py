import uuid
from datetime import datetime

from sqlalchemy import DateTime, func
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    """所有 SQLAlchemy 表模型继承此类。"""


class TimestampMixin:
    """创建时间由数据库设置，更新时间由 SQLAlchemy ORM 更新。"""

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        comment="创建时间",
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        comment="更新时间",
    )


class BaseModel(Base, TimestampMixin):
    """所有业务表模型继承此类，自动带 id + created_at + updated_at。"""

    __abstract__ = True

    id: Mapped[uuid.UUID] = mapped_column(primary_key=True, default=uuid.uuid4)
