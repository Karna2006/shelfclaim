from __future__ import annotations

from decimal import Decimal

from app.live.numeric_grounding import extract_numeric_claims, find_ungrounded_claims


def test_extracts_grouped_decimal_currency_and_percent_numbers() -> None:
    claims = extract_numeric_claims("₹1,234 and 21.5%")

    assert [claim.value for claim in claims] == [Decimal("1234"), Decimal("21.5")]


def test_number_words_and_lakh_normalize_to_tool_values() -> None:
    claims = find_ungrounded_claims("I saw one lakh books.", [{"catalogue_count": 100_000}])

    assert claims == []


def test_rounding_requires_about_or_around() -> None:
    results = [{"total": 21_450.0}]

    assert find_ungrounded_claims("around 21,500 rupees", results) == []
    assert [claim.token for claim in find_ungrounded_claims("21,500 rupees", results)] == ["21,500"]
