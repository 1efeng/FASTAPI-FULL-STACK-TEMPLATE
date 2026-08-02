import asyncio
import logging

import app.db.models  # noqa: F401

from app.core.config import settings
from app.infra.database import AsyncSessionLocal
from app.modules.user.schema import UserCreate
from app.modules.user.service import UserService

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def init() -> None:
    async with AsyncSessionLocal() as session:
        svc = UserService(session)
        existing = await svc.get_by_email(settings.FIRST_SUPERUSER)
        if not existing:
            await svc.create_user(
                UserCreate(
                    email=settings.FIRST_SUPERUSER,
                    password=settings.FIRST_SUPERUSER_PASSWORD,
                    is_superuser=True,
                )
            )
            logger.info("Superuser created")


async def main_async() -> None:
    logger.info("Creating initial data")
    await init()
    logger.info("Initial data created")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
