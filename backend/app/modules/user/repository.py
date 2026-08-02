from sqlalchemy import select

from app.core.base_repository import BaseRepository
from app.modules.user.model import User


class UserRepository(BaseRepository[User]):
    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()
