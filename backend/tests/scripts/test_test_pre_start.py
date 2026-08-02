import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

from sqlalchemy import text

from app.tests_pre_start import init, logger


def test_init_successful_connection() -> None:
    engine_mock = MagicMock()

    conn_mock = AsyncMock()
    conn_mock.__aenter__.return_value = conn_mock
    engine_mock.connect.return_value = conn_mock

    select1 = text("SELECT 1")

    with (
        patch("app.tests_pre_start.text", return_value=select1),
        patch.object(logger, "info"),
        patch.object(logger, "error"),
        patch.object(logger, "warn"),
    ):
        try:
            asyncio.run(init(engine_mock))
            connection_successful = True
        except Exception:
            connection_successful = False

        assert connection_successful, (
            "The database connection should be successful and not raise an exception."
        )

        conn_mock.execute.assert_awaited_once_with(select1)
