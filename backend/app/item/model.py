from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.base_model import BaseModel

if TYPE_CHECKING:
    from app.user.model import User


class Item(BaseModel):
    __tablename__ = "item"

    title: Mapped[str] = mapped_column(String(255), comment="标题")
    description: Mapped[str | None] = mapped_column(
        String(255), default=None, comment="描述"
    )
    owner_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("user.id", ondelete="CASCADE"), comment="所属用户ID"
    )
    owner: Mapped[User | None] = relationship(back_populates="items", lazy="selectin")
