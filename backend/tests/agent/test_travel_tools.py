from decimal import Decimal
from unittest.mock import AsyncMock, patch

import pytest
from ddgs.exceptions import DDGSException, TimeoutException
from pydantic_ai import ToolReturn

from app.agent.tools.currency import (
    CurrencyAmount,
    convert_currency,
    convert_currency_data,
)
from app.agent.tools.image_search import (
    ImageSearchResult,
    _normalize_image_results,
    image_search,
)
from app.agent.tools.search import SearchResult, web_search
from app.agent.tools.weather import get_weather


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


@pytest.mark.asyncio
async def test_web_search_clamps_results_and_emits_source_chunks(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def fake_execute_search(**kwargs: object) -> list[SearchResult]:
        observed.update(kwargs)
        return [
            SearchResult(
                title="Official result",
                url="https://example.test/official",
                snippet="verified snippet",
            )
        ]

    monkeypatch.setattr("app.agent.tools.search._execute_search", fake_execute_search)
    result = await web_search("东京 当前 开放", max_results=99)

    assert isinstance(result, ToolReturn)
    assert observed["max_results"] == 8
    assert observed["operation"] == "text"
    assert "Official result" in result.return_value
    assert result.metadata
    assert result.metadata[0].url == "https://example.test/official"


@pytest.mark.asyncio
async def test_web_search_routes_clear_news_intent_internally(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    observed: dict[str, object] = {}

    async def fake_execute_search(**kwargs: object) -> list[SearchResult]:
        observed.update(kwargs)
        return [
            SearchResult(
                title="北京新闻",
                url="https://example.test/news",
                snippet="新闻摘要",
                published_at="2026-08-15",
                source="example",
            )
        ]

    monkeypatch.setattr("app.agent.tools.search._execute_search", fake_execute_search)
    result = await web_search("北京今天有什么新闻")

    assert isinstance(result, ToolReturn)
    assert observed["operation"] == "news"
    assert "2026-08-15" in result.return_value


@pytest.mark.asyncio
async def test_web_search_timeout_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def timeout(**kwargs: object) -> list[SearchResult]:
        del kwargs
        raise TimeoutError("provider secret timeout details")

    monkeypatch.setattr("app.agent.tools.search._execute_search", timeout)
    result = await web_search("current policy")

    assert result == "SEARCH_TIMEOUT"
    assert "provider secret" not in result


@pytest.mark.asyncio
async def test_web_search_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(**kwargs: object) -> list[SearchResult]:
        del kwargs
        raise RuntimeError("raw upstream payload")

    monkeypatch.setattr("app.agent.tools.search._execute_search", fail)
    result = await web_search("current policy")

    assert result == "SEARCH_UNAVAILABLE"
    assert "raw upstream" not in result


@pytest.mark.asyncio
async def test_web_search_no_results_is_explicit(monkeypatch: pytest.MonkeyPatch) -> None:
    async def empty(**kwargs: object) -> list[SearchResult]:
        del kwargs
        return []

    monkeypatch.setattr("app.agent.tools.search._execute_search", empty)
    assert await web_search("nothing") == "NO_RESULTS"


@pytest.mark.asyncio
async def test_web_search_maps_ddgs_no_results_exception_to_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty(**kwargs: object) -> list[SearchResult]:
        del kwargs
        raise DDGSException("No results found.")

    monkeypatch.setattr("app.agent.tools.search._execute_search", empty)
    assert await web_search("nothing") == "NO_RESULTS"


@pytest.mark.asyncio
async def test_web_search_maps_ddgs_timeout_to_safe_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def timeout(**kwargs: object) -> list[SearchResult]:
        del kwargs
        raise TimeoutException("sensitive upstream timeout detail")

    monkeypatch.setattr("app.agent.tools.search._execute_search", timeout)
    assert await web_search("current policy") == "SEARCH_TIMEOUT"


def test_image_search_normalization_keeps_image_and_source_page_distinct() -> None:
    results = _normalize_image_results(
        [
            {
                "title": "故宫",
                "image": "https://img.example/fb.jpg",
                "thumbnail": "https://img.example/fb-thumb.jpg",
                "url": "https://source.example/palace",
                "width": "1600",
                "height": 900,
                "source": "source.example",
            }
        ]
    )

    assert results == [
        ImageSearchResult(
            title="故宫",
            image_url="https://img.example/fb.jpg",
            thumbnail_url="https://img.example/fb-thumb.jpg",
            source_page_url="https://source.example/palace",
            width=1600,
            height=900,
            source="source.example",
        )
    ]


@pytest.mark.asyncio
async def test_image_search_failure_is_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    async def fail(**kwargs: object) -> list[ImageSearchResult]:
        del kwargs
        raise RuntimeError("raw image backend payload")

    monkeypatch.setattr("app.agent.tools.image_search._execute_image_search", fail)
    result = await image_search("故宫")

    assert result == "IMAGE_SEARCH_UNAVAILABLE"
    assert "raw image backend" not in result


@pytest.mark.asyncio
async def test_image_search_maps_ddgs_no_results_exception_to_no_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def empty(**kwargs: object) -> list[ImageSearchResult]:
        del kwargs
        raise DDGSException("No results found.")

    monkeypatch.setattr("app.agent.tools.image_search._execute_image_search", empty)
    assert await image_search("不存在的景点") == "NO_RESULTS"


@pytest.mark.asyncio
async def test_image_search_maps_ddgs_timeout_to_safe_timeout(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    async def timeout(**kwargs: object) -> list[ImageSearchResult]:
        del kwargs
        raise TimeoutException("sensitive image timeout detail")

    monkeypatch.setattr("app.agent.tools.image_search._execute_image_search", timeout)
    assert await image_search("故宫") == "IMAGE_SEARCH_TIMEOUT"


@pytest.mark.asyncio
async def test_search_tools_are_offline_in_test_env(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.core.config import settings

    monkeypatch.setattr(settings, "APP_ENV", "test")

    async def forbidden_web(**kwargs: object) -> list[SearchResult]:
        del kwargs
        raise AssertionError("DDGS web network path must not run in tests")

    async def forbidden_images(**kwargs: object) -> list[ImageSearchResult]:
        del kwargs
        raise AssertionError("DDGS image network path must not run in tests")

    monkeypatch.setattr("app.agent.tools.search._search_ddgs", forbidden_web)
    monkeypatch.setattr("app.agent.tools.image_search._search_ddgs_images", forbidden_images)

    web_result = await web_search("offline test")
    image_result = await image_search("offline image test")

    assert isinstance(web_result, ToolReturn)
    assert isinstance(image_result, list)
    assert image_result[0].source_page_url == "https://example.test/poi"


@pytest.mark.asyncio
async def test_weather_tool_degrades_when_provider_key_is_missing() -> None:
    with patch(
        "app.agent.tools.weather._weather_api_key",
        side_effect=RuntimeError("missing"),
    ):
        result = await get_weather("东京")

    assert result == "天气查询暂时失败：RuntimeError"
