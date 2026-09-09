import asyncio
import logging

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from tenacity import after_log, before_log, retry, stop_after_attempt, wait_fixed

from app.db.session import engine

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

max_tries = 60 * 5
wait_seconds = 1


@retry(
    stop=stop_after_attempt(max_tries),
    wait=wait_fixed(wait_seconds),
    before=before_log(logger, logging.INFO),
    after=after_log(logger, logging.WARN),
)
async def init(db_engine: AsyncEngine) -> None:
    try:
        async with db_engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
    except Exception as exc:
        logger.error(exc)
        raise


async def main_async() -> None:
    logger.info("Initializing service")
    await init(engine)
    logger.info("Service finished initializing")


def main() -> None:
    asyncio.run(main_async())


if __name__ == "__main__":
    main()
