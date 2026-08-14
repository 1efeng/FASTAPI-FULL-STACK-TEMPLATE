"""Deterministic travel budget calculation.

The model selects the final itinerary and price inputs. This module only validates
and totals those inputs; it owns no destination prices and makes no travel choices.
"""

from __future__ import annotations

from decimal import Decimal
from typing import TypedDict

from pydantic import BaseModel, Field


class BudgetItem(BaseModel):
    """One price item from the itinerary selected by the main agent."""

    name: str = Field(description="预算项目名称，如东京到京都新干线")
    category: str = Field(description="分类，如 transport / hotel / food / ticket")
    amount_min: Decimal = Field(
        ge=0,
        description="单价或区间下限，必须使用 currency 指定的币种",
    )
    amount_max: Decimal | None = Field(
        default=None,
        ge=0,
        description="区间上限；固定价格可省略",
    )
    quantity: Decimal = Field(
        default=Decimal("1"),
        gt=0,
        description="数量，如住宿晚数或餐饮天数",
    )
    per_person: bool = Field(
        default=False,
        description="单价是否为每人价格；为 true 时自动乘以 people",
    )


class BudgetRange(TypedDict):
    min: int | float
    max: int | float


class BudgetLine(TypedDict):
    name: str
    category: str
    group_min: int | float
    group_max: int | float


class BudgetResult(TypedDict):
    currency: str
    people: int
    group_total: BudgetRange
    per_person_total: BudgetRange
    categories: dict[str, BudgetRange]
    items: list[BudgetLine]


def _number(value: Decimal) -> int | float:
    normalized = value.quantize(Decimal("0.01"))
    if normalized == normalized.to_integral():
        return int(normalized)
    return float(normalized)


def calculate_budget_data(
    *,
    currency: str,
    people: int,
    items: list[BudgetItem],
) -> BudgetResult:
    """Total already-selected price items without making itinerary decisions."""
    iso_currency = currency.strip().upper()
    if (
        len(iso_currency) != 3
        or not iso_currency.isascii()
        or not iso_currency.isalpha()
    ):
        raise ValueError("currency 必须使用 3 位 ISO 4217 代码，例如 JPY / CNY / USD")
    if people < 1:
        raise ValueError("people 必须大于等于 1")
    if not items:
        raise ValueError("items 不能为空")

    group_min = Decimal("0")
    group_max = Decimal("0")
    category_totals: dict[str, tuple[Decimal, Decimal]] = {}
    lines: list[BudgetLine] = []

    for item in items:
        unit_max = item.amount_max if item.amount_max is not None else item.amount_min
        if unit_max < item.amount_min:
            raise ValueError(f"{item.name} 的 amount_max 不能小于 amount_min")

        multiplier = item.quantity * (people if item.per_person else 1)
        line_min = item.amount_min * multiplier
        line_max = unit_max * multiplier
        group_min += line_min
        group_max += line_max

        category_min, category_max = category_totals.get(
            item.category,
            (Decimal("0"), Decimal("0")),
        )
        category_totals[item.category] = (
            category_min + line_min,
            category_max + line_max,
        )
        lines.append(
            BudgetLine(
                name=item.name,
                category=item.category,
                group_min=_number(line_min),
                group_max=_number(line_max),
            )
        )

    people_decimal = Decimal(people)
    return BudgetResult(
        currency=iso_currency,
        people=people,
        group_total=BudgetRange(min=_number(group_min), max=_number(group_max)),
        per_person_total=BudgetRange(
            min=_number(group_min / people_decimal),
            max=_number(group_max / people_decimal),
        ),
        categories={
            category: BudgetRange(min=_number(values[0]), max=_number(values[1]))
            for category, values in category_totals.items()
        },
        items=lines,
    )


def calculate_budget(
    currency: str,
    items: list[BudgetItem],
    people: int = 1,
) -> BudgetResult:
    """对已确定的旅行价格项目做预算汇总。

    只计算最终采用的方案；不要把未采用的备选交通、酒店或 Pass 混入
    items。工具不提供城市价格，也不判断哪个旅行方案更好。
    """
    return calculate_budget_data(currency=currency, people=people, items=items)
