import uuid

from httpx import AsyncClient

from app.core.config import settings


async def _create_item(
    client: AsyncClient,
    headers: dict[str, str],
    *,
    title: str = "Copy sample",
) -> dict[str, str]:
    response = await client.post(
        f"{settings.API_V1_STR}/items/",
        headers=headers,
        json={"title": title, "description": "Example item"},
    )
    assert response.status_code == 201
    return response.json()


async def test_item_crud_for_owner(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    created = await _create_item(client, normal_user_token_headers)
    item_id = created["id"]

    response = await client.get(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Copy sample"

    response = await client.patch(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
        json={"title": "Updated sample"},
    )
    assert response.status_code == 200
    assert response.json()["title"] == "Updated sample"

    response = await client.get(
        f"{settings.API_V1_STR}/items/",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    assert body["count"] == 1
    assert [item["id"] for item in body["data"]] == [item_id]

    response = await client.delete(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 200
    assert response.json() == {"message": "Item deleted successfully"}


async def test_normal_user_cannot_access_another_users_item(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    created = await _create_item(client, superuser_token_headers, title="Private")
    item_id = created["id"]

    response = await client.get(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403
    assert response.json()["detail"] == "Not enough permissions"

    response = await client.patch(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
        json={"title": "Forbidden"},
    )
    assert response.status_code == 403

    response = await client.delete(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 403


async def test_item_not_found(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
) -> None:
    item_id = uuid.uuid4()

    response = await client.get(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404
    assert response.json()["detail"] == "Item not found"

    response = await client.patch(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
        json={"title": "Missing"},
    )
    assert response.status_code == 404

    response = await client.delete(
        f"{settings.API_V1_STR}/items/{item_id}",
        headers=normal_user_token_headers,
    )
    assert response.status_code == 404


async def test_superuser_can_list_all_items(
    client: AsyncClient,
    normal_user_token_headers: dict[str, str],
    superuser_token_headers: dict[str, str],
) -> None:
    normal_item = await _create_item(
        client, normal_user_token_headers, title="Normal user item"
    )
    super_item = await _create_item(
        client, superuser_token_headers, title="Superuser item"
    )

    response = await client.get(
        f"{settings.API_V1_STR}/items/",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
    body = response.json()
    ids = {item["id"] for item in body["data"]}
    assert body["count"] == 2
    assert ids == {normal_item["id"], super_item["id"]}

    response = await client.get(
        f"{settings.API_V1_STR}/items/{normal_item['id']}",
        headers=superuser_token_headers,
    )
    assert response.status_code == 200
