from __future__ import annotations

import json
from decimal import Decimal

import pytest
from app.pipeline.stages.s07_price_books import price_sweep
from app.pricing.book_pricer import PricedOffer, estimate_book_price
from app.pricing.item_pricer import estimate_item_range
from app.pricing.providers.serpapi import SearchPayload
from app.settings import Settings, YamlSettings


def test_book_estimate_filters_digital_wrong_title_and_iqr_outlier() -> None:
    offers = [
        PricedOffer("The Example Book", Decimal(price), "INR", "Shop", f"https://x/{price}", "new")
        for price in ("10", "11", "12", "1000")
    ]
    offers.append(
        PricedOffer(
            "The Example Book Kindle edition", Decimal("1"), "INR", "Shop", "https://x/k", "new"
        )
    )
    offers.append(PricedOffer("Different title", Decimal("8"), "INR", "Shop", "https://x/d", "new"))

    result = estimate_book_price("The Example Book", offers, used=False)

    assert result.amount == Decimal("11")
    assert [offer.amount for offer in result.offers] == [
        Decimal("10"),
        Decimal("11"),
        Decimal("12"),
    ]


def test_item_art_requires_print_statement_and_template_needs_three_offers() -> None:
    art = estimate_item_range(
        category="framed_art", brand_model="", material=None, offers=[], is_artwork=True
    )
    offer = PricedOffer("metal lamp", Decimal("10"), "INR", "Shop", "https://x", "new")
    template = estimate_item_range(
        category="lamp", brand_model="", material="metal", offers=[offer]
    )

    assert art.status == "needs_appraisal"
    assert template.status == "needs_appraisal"
    assert template.reason == "fewer_than_three_template_offers"


class FakePricing:
    def __init__(self) -> None:
        self.searches = []

    async def shopping(self, query, locale):
        self.searches.append(("shopping", query))
        data = {
            "shopping_results": [
                {
                    "title": "Example Book",
                    "extracted_price": 500,
                    "currency": "INR",
                    "source": "Book Shop",
                    "link": "https://shop.test/book",
                    "condition": "new",
                }
            ]
        }
        return SearchPayload(
            data, json.dumps(data).encode(), "https://serpapi.com/search.json?api_key=REDACTED"
        )

    async def ebay(self, query, domain):
        self.searches.append(("ebay", domain))
        return SearchPayload({}, b"{}", "https://serpapi.com/search.json?api_key=REDACTED")

    async def fx(self, from_currency, to_currency):
        raise AssertionError("FX is not needed for a search-limit-one run")


@pytest.mark.asyncio
async def test_pricing_limit_caps_searches_and_saves_snapshot(tmp_path) -> None:
    (tmp_path / "sweep.json").write_text(json.dumps({"country": "IN", "currency": "INR"}))
    (tmp_path / "s06_identification.json").write_text(
        json.dumps(
            {
                "books": {
                    f"b_{index:04d}": {
                        "status": "identified",
                        "title": "Example Book",
                        "authors": ["Author"],
                        "spine_text_raw": "Example Book",
                    }
                    for index in range(3)
                }
            }
        )
    )
    fake = FakePricing()

    output = await price_sweep(
        tmp_path, Settings(config=YamlSettings(), _env_file=None), fake, limit=1
    )

    result = json.loads(output.read_text())
    assert len(fake.searches) == 1
    assert result["searches_used"] == 1
    quote = result["books"]["b_0000"]["new"]
    assert quote["amount"] == 500
    assert quote["snapshot_path"] == "evidence/prices/b_0000_new.json"
    assert (tmp_path / quote["snapshot_path"]).is_file()
