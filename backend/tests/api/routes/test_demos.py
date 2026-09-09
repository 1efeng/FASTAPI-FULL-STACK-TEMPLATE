import uuid

from httpx import AsyncClient

from app.core.config import settings


async def _create_demo(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "Copy sample",
) -> dict[str, str]:
    response = await client.post(
        f"{settings.API_V1_STR}/demos/",
        headers=headers,
        json={"title": title, "description": "Example demo"},
    )
    assert response.status_code == 201
    return response.json()


async def test_demo_crud_for_owner(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    created = await _create_demo(client, normal_user_token_headers)
    demo_id = created["id"]

    response = await client.get(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Copy sample"

    response = await client.patch(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
        json={"title": "Updated sample"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated sample"

    response = await client.get(
        f"{settings.API_V1_STR}/demos/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert [demo["id"] for demo in body["data"]] == [demo_id]

    response = await client.delete(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Demo deleted successfully"}


async def test_normal_user_cannot_access_another_users_demo(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    created = await _create_demo(client, superuser_token_headers, title="Private")
    demo_id = created["id"]

    response = await client.get(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions"

    response = await client.patch(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
        json={"title": "Forbidden"},
    )
    assert response.status_code == 403

    response = await client.delete(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403


async def test_demo_not_found(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    demo_id = uuid.uuid4()

    response = await client.get(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Demo not found"

    response = await client.patch(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
        json={"title": "Missing"},
    )
    assert response.status_code == 404

    response = await client.delete(
        f"{settings.API_V1_STR}/demos/{demo_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


async def test_superuser_can_list_all_demos(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    normal_demo = await _create_demo(
        client, normal_user_token_headers, title="Normal user demo"
    )
    super_demo = await _create_demo(
        client, superuser_token_headers, title="Superuser demo"
    )

    response = await client.get(
        f"{settings.API_V1_STR}/demos/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    ids = {demo["id"] for demo in body["data"]}
    assert body["count"] == 2
    assert ids == {normal_demo["id"], super_demo["id"]}

    response = await client.get(
        f"{settings.API_V1_STR}/demos/{normal_demo['id']}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
