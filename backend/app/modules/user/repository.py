from sqlalchemy import func, select

from app.core.base_repository import BaseRepository
from app.modules.user.model import User


class UserRepository(BaseRepository[User]):
    async def get_by_email(self, email: str) -> User | None:
        statement = select(User).where(func.lower(User.email) == email.casefold())
        result = await self.db.execute(statement)
        return result.scalar_one_or_none()
