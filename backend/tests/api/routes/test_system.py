from httpx import AsyncClient

from app.core.config import settings


async def test_health_live(client: AsyncClient) -> None:
    response = await client.get(f"{settings.API_V1_STR}/system/health/live")
    assert response.status_code == 200
    assert response.json() is True


async def test_health_ready(client: AsyncClient) -> None:
    response = await client.get(f"{settings.API_V1_STR}/system/health/ready")
    assert response.status_code == 200
    assert response.json() is True


async def test_legacy_health_check(client: AsyncClient) -> None:
    response = await client.get(f"{settings.API_V1_STR}/system/health-check/")
    assert response.status_code == 200
    assert response.json() is True
