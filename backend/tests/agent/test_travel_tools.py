from decimal import Decimal
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from app.agent.tools.currency import (
    CurrencyAmount,
    convert_currency,
    convert_currency_data,
)
from app.agent.tools.image_search import ImageSearchResult, image_search
from app.agent.tools.search import web_search
from app.agent.tools.weather import get_weather


class _FakeResponse:
    def __init__(self, payload: dict[str, object]) -> None:
        self._payload = payload

    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict[str, object]:
        return self._payload


class _FakeClient:
    def __init__(
        self,
        payload: dict[str, object] | None = None,
        error: Exception | None = None,
    ) -> None:
        self._payload = payload or {}
        self._error = error
        self.calls: list[dict[str, object]] = []

    async def __aenter__(self) -> _FakeClient:
        return self

    async def __aexit__(self, *args: object) -> None:
        return None

    async def get(self, url: str, params: dict[str, object]) -> _FakeResponse:
        self.calls.append({"url": url, "params": params})
        if self._error is not None:
            raise self._error
        return _FakeResponse(self._payload)


@pytest.mark.asyncio
async def test_currency_conversion_uses_one_rate_for_every_amount() -> None:
    rate = AsyncMock(return_value=(Decimal("0.05"), "2026-08-14", "fake"))
    with patch("app.agent.tools.currency.get_exchange_rate", rate):
        result = await convert_currency_data(
            from_currency="日元",
            to_currency="CNY",
            amounts=[
                CurrencyAmount(name="交通", amount_min=Decimal("10000")),
                CurrencyAmount(
                    name="住宿",
                    amount_min=Decimal("20000"),
                    amount_max=Decimal("24000"),
                ),
            ],
        )

    rate.assert_awaited_once_with(base="JPY", quote="CNY")
    assert result["rate"] == 0.05
    assert result["amounts"] == [
        {
            "name": "交通",
            "from_min": 10000,
            "from_max": 10000,
            "to_min": 500,
            "to_max": 500,
        },
        {
            "name": "住宿",
            "from_min": 20000,
            "from_max": 24000,
            "to_min": 1000,
            "to_max": 1200,
        },
    ]


@pytest.mark.asyncio
async def test_currency_tool_degrades_to_text_on_provider_failure() -> None:
    with patch(
        "app.agent.tools.currency.get_exchange_rate",
        AsyncMock(side_effect=TimeoutError),
    ):
        result = await convert_currency(
            from_currency="JPY",
            amounts=[CurrencyAmount(name="预算", amount_min=Decimal("100"))],
        )

    assert result == "汇率换算暂时失败：TimeoutError"


def _search_payload(
    rows: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {"results": rows or []}


@pytest.mark.asyncio
async def test_web_search_returns_structured_results(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(
        _search_payload(
            [
                {
                    "title": "Official result",
                    "url": "https://example.test/official",
                    "content": "verified snippet",
                },
                {
                    "title": "Second result",
                    "url": "https://example.test/second",
                    "content": "more info",
                },
            ]
        )
    )
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    result = await web_search("东京 当前 开放")

    assert isinstance(result, list)
    assert result == [
        {
            "title": "Official result",
            "url": "https://example.test/official",
            "content": "verified snippet",
        },
        {
            "title": "Second result",
            "url": "https://example.test/second",
            "content": "more info",
        },
    ]
    params = client.calls[0]["params"]
    assert params["q"] == "东京 当前 开放"
    assert params["format"] == "json"
    assert "categories" not in params


@pytest.mark.asyncio
async def test_web_search_routes_news_intent_to_news_category(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _search_payload(
            [
                {
                    "title": "北京新闻",
                    "url": "https://example.test/beijing-news",
                    "content": "latest",
                }
            ]
        )
    )
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    await web_search("2026年8月最新北京新闻")

    params = client.calls[0]["params"]
    assert params["categories"] == "news"
    assert params["time_range"] == "month"


@pytest.mark.asyncio
async def test_web_search_clamps_results_to_max(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {"title": f"result {i}", "url": f"https://example.test/{i}", "content": "x"}
        for i in range(10)
    ]
    client = _FakeClient(_search_payload(rows))
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    result = await web_search("东京 当前 开放", max_results=3)

    assert isinstance(result, list)
    assert len(result) == 3
    assert result[0]["title"] == "result 0"
    assert all(row["url"] != "https://example.test/3" for row in result)


@pytest.mark.asyncio
async def test_web_search_skips_incomplete_rows(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _FakeClient(
        _search_payload(
            [
                {"title": "has url", "url": "https://example.test/a", "content": "ok"},
                {"url": ""},
                {},
            ]
        )
    )
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    result = await web_search("skip broken rows")

    assert isinstance(result, list)
    assert len(result) == 1
    assert result[0]["title"] == "has url"


@pytest.mark.asyncio
async def test_web_search_empty_results_returns_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_search_payload([]))
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    assert await web_search("nothing") == "NO_RESULTS"


@pytest.mark.asyncio
async def test_web_search_failure_returns_safe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(error=RuntimeError("raw upstream provider.invalid payload"))
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    result = await web_search("current policy")

    assert result == "SEARCH_UNAVAILABLE"
    assert "provider.invalid" not in result


@pytest.mark.asyncio
async def test_web_search_timeout_returns_safe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(error=httpx.TimeoutException("provider secret timeout"))
    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", lambda **_: client)

    result = await web_search("current policy")

    assert result == "SEARCH_UNAVAILABLE"
    assert "provider secret" not in result


@pytest.mark.asyncio
async def test_web_search_offline_in_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "test")

    async def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("network must not run in tests")

    monkeypatch.setattr("app.agent.tools.search.httpx.AsyncClient", forbidden)

    result = await web_search("offline test")

    assert isinstance(result, list)
    assert result[0]["url"] == "https://example.test/search"
    assert "offline test" in result[0]["content"]


@pytest.mark.asyncio
async def test_image_search_returns_normalized_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _search_payload(
            [
                {
                    "title": "故宫",
                    "img_src": "https://img.example/fb.jpg",
                    "thumbnail_src": "https://img.example/fb-thumb.jpg",
                    "url": "https://source.example/palace",
                    "resolution": "760×420",
                    "engine": "bing images",
                }
            ]
        )
    )
    monkeypatch.setattr(
        "app.agent.tools.image_search.httpx.AsyncClient", lambda **_: client
    )

    result = await image_search("故宫")

    assert result == [
        ImageSearchResult(
            title="故宫",
            image_url="https://img.example/fb.jpg",
            thumbnail_url="https://img.example/fb-thumb.jpg",
            source_page_url="https://source.example/palace",
            width=760,
            height=420,
            source="bing images",
        )
    ]
    params = client.calls[0]["params"]
    assert params["categories"] == "images"
    assert params["format"] == "json"


@pytest.mark.asyncio
async def test_image_search_clamps_results_to_max(monkeypatch: pytest.MonkeyPatch) -> None:
    rows = [
        {
            "title": f"img {i}",
            "img_src": f"https://img.example/{i}.jpg",
            "url": f"https://source.example/{i}",
        }
        for i in range(10)
    ]
    client = _FakeClient(_search_payload(rows))
    monkeypatch.setattr(
        "app.agent.tools.image_search.httpx.AsyncClient", lambda **_: client
    )

    result = await image_search("故宫", max_results=3)

    assert isinstance(result, list)
    assert len(result) == 3


@pytest.mark.asyncio
async def test_image_search_skips_rows_without_image(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(
        _search_payload(
            [
                {"title": "no img", "url": "https://source.example/a"},
                {"title": "ok", "img_src": "https://img.example/a.jpg",
                 "url": "https://source.example/a"},
            ]
        )
    )
    monkeypatch.setattr(
        "app.agent.tools.image_search.httpx.AsyncClient", lambda **_: client
    )

    result = await image_search("故宫")

    assert isinstance(result, list)
    assert len(result) == 1


@pytest.mark.asyncio
async def test_image_search_empty_returns_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(_search_payload([]))
    monkeypatch.setattr(
        "app.agent.tools.image_search.httpx.AsyncClient", lambda **_: client
    )

    assert await image_search("不存在的景点") == "NO_RESULTS"


@pytest.mark.asyncio
async def test_image_search_failure_returns_safe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(error=RuntimeError("raw image backend payload"))
    monkeypatch.setattr(
        "app.agent.tools.image_search.httpx.AsyncClient", lambda **_: client
    )

    result = await image_search("故宫")

    assert result == "IMAGE_SEARCH_UNAVAILABLE"
    assert "raw image backend" not in result


@pytest.mark.asyncio
async def test_image_search_timeout_returns_safe_unavailable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    client = _FakeClient(error=httpx.TimeoutException("sensitive image detail"))
    monkeypatch.setattr(
        "app.agent.tools.image_search.httpx.AsyncClient", lambda **_: client
    )

    result = await image_search("故宫")

    assert result == "IMAGE_SEARCH_UNAVAILABLE"
    assert "sensitive image" not in result


@pytest.mark.asyncio
async def test_image_search_offline_in_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "test")

    async def forbidden(*args: object, **kwargs: object) -> object:
        raise AssertionError("network must not run in tests")

    monkeypatch.setattr("app.agent.tools.image_search.httpx.AsyncClient", forbidden)

    result = await image_search("offline image test")

    assert isinstance(result, list)
    assert result[0].source_page_url == "https://example.test/poi"


@pytest.mark.asyncio
async def test_weather_tool_degrades_when_provider_key_is_missing() -> None:
    with patch(
        "app.agent.tools.weather._weather_api_key",
        side_effect=RuntimeError("missing"),
    ):
        result = await get_weather("东京")

    assert result == "天气查询暂时失败：RuntimeError"