from __future__ import annotations

from typing import TYPE_CHECKING

from sqlalchemy import Index, String, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import BaseModel

if TYPE_CHECKING:
    from app.item.model import Item


class User(BaseModel):
    __tablename__ = "user"

    email: Mapped[str] = mapped_column(String(255))
    is_active: Mapped[bool] = mapped_column(default=True)
    is_superuser: Mapped[bool] = mapped_column(default=False)
    full_name: Mapped[str | None] = mapped_column(String(255), default=None)
    hashed_password: Mapped[str] = mapped_column(String(128))

    __table_args__ = (Index("ix_user_email", func.lower(email), unique=True),)

    items: Mapped[list[Item]] = relationship(
        back_populates="owner",
        cascade="all, delete-orphan",
        passive_deletes=True,
        lazy="raise",
    )
