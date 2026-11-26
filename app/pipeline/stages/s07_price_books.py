"""Price identified books from provider-backed new and used offers.

Input: catalogue matches, locale rules and search providers. Output: S7 quotes
with raw evidence snapshots and appraisal/price review codes; no model prices.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Protocol, cast

import yaml
from app.pipeline.context import StageContext
from app.pricing.book_pricer import Estimate, PricedOffer, estimate_book_price, parse_serp_offers
from app.pricing.providers.serpapi import SearchPayload, SerpApiProvider


class BookPricingProvider(Protocol):
    async def shopping(self, query: str, locale: dict[str, object]) -> SearchPayload: ...
    async def ebay(self, query: str, domain: str) -> SearchPayload: ...
    async def fx(self, from_currency: str, to_currency: str) -> SearchPayload: ...


async def run(ctx: StageContext, *, country: str | None = None, limit: int = 10) -> Path:
    """Run book repricing with a hard maximum of forty provider searches."""
    if not (ctx.sweep_dir / "s06_identification.json").is_file():
        raise FileNotFoundError("S6 identification is required before pricing")
    injected = ctx.clients.get("pricing")
    identity = json.loads((ctx.sweep_dir / "s06_identification.json").read_text(encoding="utf-8"))
    has_identified = any(
        row.get("status") == "identified" and row.get("title")
        for row in identity.get("books", {}).values()
    )
    provider = (
        cast(BookPricingProvider, injected)
        if injected is not None
        else SerpApiProvider(ctx.settings)
        if has_identified and limit > 0
        else _NoPricingProvider()
    )
    return await price_sweep(ctx.sweep_dir, ctx.settings, provider, country=country, limit=limit)


class _NoPricingProvider:
    """Prevent network setup when there are no identified books to price."""

    async def shopping(self, query: str, locale: dict[str, object]) -> SearchPayload:
        raise RuntimeError("No book searches are expected for this sweep")

    async def ebay(self, query: str, domain: str) -> SearchPayload:
        raise RuntimeError("No book searches are expected for this sweep")

    async def fx(self, from_currency: str, to_currency: str) -> SearchPayload:
        raise RuntimeError("No FX request is expected for this sweep")


async def price_sweep(
    sweep_dir: Path,
    settings: Any,
    provider: BookPricingProvider,
    *,
    country: str | None = None,
    limit: int = 10,
) -> Path:
    """Persist evidence-backed book estimates and appraisal decisions."""
    identification_path = sweep_dir / "s06_identification.json"
    if not identification_path.is_file():
        raise FileNotFoundError("S6 identification is required before pricing")
    identification = json.loads(identification_path.read_text(encoding="utf-8"))
    sweep = json.loads((sweep_dir / "sweep.json").read_text(encoding="utf-8"))
    selected_country = (country or sweep["country"]).upper()
    locale_path = Path("config/locales") / f"{selected_country}.yaml"
    locale = yaml.safe_load(locale_path.read_text(encoding="utf-8"))
    searches_left = min(max(0, limit), 40)
    evidence_dir = sweep_dir / "evidence" / "prices"
    evidence_dir.mkdir(parents=True, exist_ok=True)
    statements = _statement_kinds(sweep_dir)
    timestamp = datetime.now(UTC).isoformat()
    books: dict[str, Any] = {}
    review: list[dict[str, str]] = []

    for book_id, book in identification.get("books", {}).items():
        title = str(book.get("title", ""))
        authors = book.get("authors", [])
        author = " ".join(authors) if isinstance(authors, list) else str(authors)
        pre_reasons = _pre_appraisal_reasons(book, statements, locale.get("appraisal", {}))
        if book.get("status") != "identified" or not title:
            books[book_id] = _empty_quotes(locale["currency"], timestamp, "not_found")
            books[book_id]["appraisal"] = {"flag": False, "reasons": []}
            review.append({"ref_id": book_id, "code": "unidentified_spine"})
            continue
        if pre_reasons:
            books[book_id] = _empty_quotes(locale["currency"], timestamp, "skipped_appraisal")
            books[book_id]["appraisal"] = {"flag": True, "reasons": pre_reasons}
            review.append({"ref_id": book_id, "code": "needs_appraisal:pre_rule"})
            continue
        query = f"{title} {author} book".strip()
        empty = _empty_quotes(locale["currency"], timestamp, "not_found")
        new_quote = empty["new"]
        used_quote = empty["used"]
        try:
            if searches_left > 0:
                searches_left -= 1
                payload = await provider.shopping(query, locale["shopping"])
                new_quote = _quote_from_payload(
                    payload,
                    parse_serp_offers(payload.data, used=False),
                    title,
                    used=False,
                    currency=locale["currency"],
                    snapshot=evidence_dir / f"{book_id}_new.json",
                    timestamp=timestamp,
                )
            if searches_left > 0:
                market = locale.get("used_market", {})
                domain = "ebay.co.uk" if market.get("fallback_marketplace") else "ebay.co.uk"
                searches_left -= 1
                payload = await provider.ebay(query, domain)
                used_quote = _quote_from_payload(
                    payload,
                    parse_serp_offers(payload.data, used=True),
                    title,
                    used=True,
                    currency=locale["currency"],
                    snapshot=evidence_dir / f"{book_id}_used.json",
                    timestamp=timestamp,
                )
                if selected_country == "IN" and used_quote["amount"] is not None:
                    fx_payload = await provider.fx("GBP", "INR")
                    (evidence_dir / "fx_GBP_INR.json").write_bytes(fx_payload.raw)
                    rate = Decimal(str(fx_payload.data["rates"]["INR"]))
                    original = Decimal(str(used_quote["amount"]))
                    used_quote = _convert_quote(
                        used_quote,
                        original,
                        rate,
                        fx_payload,
                        evidence_dir / f"{book_id}_used.json",
                    )
                    review.append({"ref_id": book_id, "code": "price_converted"})
        except Exception as exc:
            books[book_id] = {
                "new": new_quote,
                "used": used_quote,
                "appraisal": {"flag": False, "reasons": []},
                "provider_error": type(exc).__name__,
            }
            review.append({"ref_id": book_id, "code": "price_provider_unavailable"})
            continue
        appraisal = _post_appraisal_reasons(new_quote, used_quote, locale.get("appraisal", {}))
        if appraisal:
            empty = _empty_quotes(locale["currency"], timestamp, "skipped_appraisal")
            new_quote = empty["new"]
            used_quote = empty["used"]
            review.append({"ref_id": book_id, "code": "needs_appraisal:post_rule"})
        if new_quote["price_status"] == "not_found" or used_quote["price_status"] == "not_found":
            review.append({"ref_id": book_id, "code": "price_not_found"})
        books[book_id] = {
            "new": new_quote,
            "used": used_quote,
            "appraisal": {"flag": bool(appraisal), "reasons": appraisal},
            "query": query,
        }
    output = sweep_dir / "s07_book_prices.json"
    output.write_text(
        json.dumps(
            {
                "books": books,
                "review_queue": review,
                "searches_used": min(max(0, limit), 40) - searches_left,
            },
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return output


def _quote_from_payload(
    payload: SearchPayload,
    offers: list[PricedOffer],
    title: str,
    *,
    used: bool,
    currency: str,
    snapshot: Path,
    timestamp: str,
) -> dict[str, Any]:
    snapshot.parent.mkdir(parents=True, exist_ok=True)
    snapshot.write_bytes(payload.raw)
    estimate = estimate_book_price(title, offers, used=used)
    return _quote(estimate, currency, used, payload.request_url, snapshot, timestamp)


def _quote(
    estimate: Estimate,
    currency: str,
    used: bool,
    search_url: str,
    snapshot: Path,
    timestamp: str,
) -> dict[str, Any]:
    representative = estimate.representative
    return {
        "amount": float(estimate.amount) if estimate.amount is not None else None,
        "currency": currency,
        "source": f"{representative.merchant} via SerpAPI" if representative else "SerpAPI",
        "url": representative.url if representative else search_url,
        "retrieved_at": timestamp,
        "converted": False,
        "original_amount": None,
        "original_currency": None,
        "fx": None,
        "n_offers": len(estimate.offers),
        "snapshot_path": _relative_evidence_path(snapshot),
        "price_status": "priced" if estimate.amount is not None else "not_found",
        "condition_assumed": "Used – Good" if used else None,
        "offers_used": [
            {
                "title": offer.title,
                "price": float(offer.amount),
                "merchant": offer.merchant,
                "url": offer.url,
            }
            for offer in estimate.offers
        ],
    }


def _empty_quotes(currency: str, timestamp: str, status: str) -> dict[str, Any]:
    def quote(used: bool) -> dict[str, Any]:
        return {
            "amount": None,
            "currency": currency,
            "source": "",
            "url": "",
            "retrieved_at": timestamp,
            "converted": False,
            "original_amount": None,
            "original_currency": None,
            "fx": None,
            "n_offers": 0,
            "snapshot_path": "",
            "price_status": status,
            "condition_assumed": "Used – Good" if used else None,
        }

    return {
        "new": quote(False),
        "used": quote(True),
    }


def _convert_quote(
    quote: dict[str, Any], original: Decimal, rate: Decimal, fx: SearchPayload, snapshot: Path
) -> dict[str, Any]:
    converted = dict(quote)
    converted.update(
        {
            "amount": float(original * rate),
            "currency": "INR",
            "converted": True,
            "original_amount": float(original),
            "original_currency": "GBP",
            "fx": {
                "from_currency": "GBP",
                "to_currency": "INR",
                "rate": float(rate),
                "rate_date": fx.data.get("date", ""),
                "source": "Frankfurter",
                "url": fx.request_url,
            },
            "snapshot_path": _relative_evidence_path(snapshot),
        }
    )
    return converted


def _statement_kinds(sweep_dir: Path) -> set[str]:
    path = sweep_dir / "user_statements.jsonl"
    if not path.is_file():
        return set()
    return {
        str(item.get("kind", ""))
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
        for item in [json.loads(line)]
    }


def _pre_appraisal_reasons(
    book: dict[str, Any], statements: set[str], rules: dict[str, Any]
) -> list[str]:
    text = str(book.get("spine_text_raw", "")).casefold()
    reasons = [kind for kind in ("signed", "first_edition", "rare") if kind in statements]
    if any(term in text for term in ("signed", "first edition", "limited edition")):
        reasons.append("spine_claim")
    year = (book.get("chosen") or {}).get("year")
    if isinstance(year, int) and year < int(rules.get("min_year", 1950)):
        reasons.append("older_publication_no_edition_confirmation")
    return reasons


def _post_appraisal_reasons(
    new: dict[str, Any], used: dict[str, Any], rules: dict[str, Any]
) -> list[str]:
    if used.get("amount") is None:
        return []
    reasons = []
    if used["amount"] > float(rules.get("used_value_threshold", float("inf"))):
        reasons.append("used_value_threshold")
    if new.get("amount") and used["amount"] > new["amount"] * float(
        rules.get("used_over_new_ratio", float("inf"))
    ):
        reasons.append("used_over_new_ratio")
    return reasons


def _relative_evidence_path(path: Path) -> str:
    parts = path.parts
    try:
        index = parts.index("evidence")
        return Path(*parts[index:]).as_posix()
    except ValueError:
        return ""
