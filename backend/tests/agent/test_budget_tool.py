from decimal import Decimal

import pytest

from app.agent.tools.budget import BudgetItem, calculate_budget


def test_calculate_budget_totals_ranges_categories_and_people() -> None:
    result = calculate_budget(
        currency="jpy",
        people=2,
        items=[
            BudgetItem(
                name="酒店",
                category="hotel",
                amount_min=Decimal("10000"),
                amount_max=Decimal("12000"),
                quantity=Decimal("2"),
            ),
            BudgetItem(
                name="门票",
                category="ticket",
                amount_min=Decimal("1500"),
                per_person=True,
            ),
        ],
    )

    assert result["currency"] == "JPY"
    assert result["group_total"] == {"min": 23000, "max": 27000}
    assert result["per_person_total"] == {"min": 11500, "max": 13500}
    assert result["categories"] == {
        "hotel": {"min": 20000, "max": 24000},
        "ticket": {"min": 3000, "max": 3000},
    }


def test_calculate_budget_rejects_invalid_currency() -> None:
    with pytest.raises(ValueError, match="ISO 4217"):
        calculate_budget(
            currency="人民币",
            items=[
                BudgetItem(
                    name="酒店",
                    category="hotel",
                    amount_min=Decimal("100"),
                )
            ],
        )


def test_calculate_budget_rejects_reversed_range() -> None:
    with pytest.raises(ValueError, match="amount_max"):
        calculate_budget(
            currency="CNY",
            items=[
                BudgetItem(
                    name="酒店",
                    category="hotel",
                    amount_min=Decimal("200"),
                    amount_max=Decimal("100"),
                )
            ],
        )
