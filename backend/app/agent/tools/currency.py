"""Deterministic currency conversion using one current reference rate."""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

import httpx
from pydantic import BaseModel, Field

from app.core.config import settings

_CURRENCY_ALIASES = {
    "人民币": "CNY",
    "人民币元": "CNY",
    "元": "CNY",
    "日元": "JPY",
    "日币": "JPY",
    "美元": "USD",
    "欧元": "EUR",
    "英镑": "GBP",
    "韩元": "KRW",
    "泰铢": "THB",
    "新加坡元": "SGD",
    "新币": "SGD",
    "港币": "HKD",
    "港元": "HKD",
    "澳元": "AUD",
}


class CurrencyAmount(BaseModel):
    name: str = Field(description="金额名称，如人均总预算")
    amount_min: Decimal = Field(ge=0, description="原币种金额或区间下限")
    amount_max: Decimal | None = Field(
        default=None,
        ge=0,
        description="区间上限；固定金额可省略",
    )


class ConvertedAmount(TypedDict):
    name: str
    from_min: int | float
    from_max: int | float
    to_min: int | float
    to_max: int | float


class CurrencyResult(TypedDict):
    from_currency: str
    to_currency: str
    rate: int | float
    rate_date: str
    source: str
    amounts: list[ConvertedAmount]


def normalize_currency(value: str) -> str:
    raw = value.strip()
    iso = _CURRENCY_ALIASES.get(raw, raw.upper())
    if len(iso) != 3 or not iso.isascii() or not iso.isalpha():
        raise ValueError(f"无法识别币种：{value}；请使用 ISO 4217 代码")
    return iso


def _number(value: Decimal) -> int | float:
    normalized = value.quantize(Decimal("0.01"))
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


async def get_exchange_rate(
    *,
    base: str,
    quote: str,
) -> tuple[Decimal, str, str]:
    if base == quote:
        return Decimal("1"), "same-currency", "identity"

    async with httpx.AsyncClient(timeout=10.0) as client:
        response = await client.get(
            f"{settings.FX_BASE_URL.rstrip('/')}/rate/{base}/{quote}"
        )
        response.raise_for_status()
        payload = response.json()

    response_base = str(payload.get("base") or "").upper()
    response_quote = str(payload.get("quote") or "").upper()
    if response_base != base or response_quote != quote:
        raise RuntimeError(f"汇率响应币种不匹配：{response_base}/{response_quote}")
    return (
        Decimal(str(payload["rate"])),
        str(payload.get("date") or "unknown"),
        "frankfurter",
    )


async def convert_currency_data(
    *,
    from_currency: str,
    to_currency: str,
    amounts: list[CurrencyAmount],
) -> CurrencyResult:
    """Convert every item using exactly one fetched rate."""
    base = normalize_currency(from_currency)
    quote = normalize_currency(to_currency)
    rate, rate_date, source = await get_exchange_rate(base=base, quote=quote)

    converted: list[ConvertedAmount] = []
    for item in amounts:
        amount_max = item.amount_max if item.amount_max is not None else item.amount_min
        if amount_max < item.amount_min:
            raise ValueError(f"{item.name} 的 amount_max 不能小于 amount_min")
        converted.append(
            ConvertedAmount(
                name=item.name,
                from_min=_number(item.amount_min),
                from_max=_number(amount_max),
                to_min=_number(item.amount_min * rate),
                to_max=_number(amount_max * rate),
            )
        )

    return CurrencyResult(
        from_currency=base,
        to_currency=quote,
        rate=_number(rate),
        rate_date=rate_date,
        source=source,
        amounts=converted,
    )


async def convert_currency(
    from_currency: str,
    amounts: list[CurrencyAmount],
    to_currency: str = "CNY",
) -> CurrencyResult | str:
    """按同一条当前参考汇率批量换算已确认的当地货币金额。

    当地货币仍是事实价格；换算只作辅助参考，失败时不得猜测汇率。
    """
    try:
        return await convert_currency_data(
            from_currency=from_currency,
            to_currency=to_currency,
            amounts=amounts,
        )
    except Exception as exc:
        return f"汇率换算暂时失败：{type(exc).__name__}"
