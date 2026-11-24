"""Record stage latency and provider costs without inventing unit prices.

Input: stage names, provider usage and `config/pricing_rates.yaml`. Output:
serializable per-sweep telemetry. Implements `docs/04_ARCHITECTURE.md` §8.
"""

from __future__ import annotations

import time
from collections.abc import Iterator
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path
from typing import Any

import yaml


class Ledger:
    def __init__(self, rates_path: Path = Path("config/pricing_rates.yaml")) -> None:
        self._rates_path = rates_path
        self._stages: dict[str, dict[str, Any]] = {}
        self._costs: list[dict[str, Any]] = []

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        started = time.perf_counter()
        status = "done"
        try:
            yield
        except Exception:
            status = "failed"
            raise
        finally:
            ended = time.perf_counter()
            self._stages[name] = {
                "duration_s": round(ended - started, 6),
                "status": status,
            }

    def cost(self, provider: str, units: float, unit_price_key: str) -> None:
        """Record usage; TODO/missing rates remain unknown instead of becoming zero."""
        rate_doc: dict[str, Any] = {}
        if self._rates_path.exists():
            loaded = yaml.safe_load(self._rates_path.read_text(encoding="utf-8")) or {}
            if isinstance(loaded, dict):
                rate_doc = loaded
        rate = rate_doc.get(unit_price_key, {})
        raw_price = rate.get("usd") if isinstance(rate, dict) else None
        try:
            unit_price = Decimal(str(raw_price))
        except Exception:
            unit_price = None
        cost_usd = Decimal(str(units)) * unit_price if unit_price is not None else None
        self._costs.append(
            {
                "provider": provider,
                "units": units,
                "unit": rate.get("unit") if isinstance(rate, dict) else None,
                "unit_price_usd": float(unit_price) if unit_price is not None else None,
                "cost_usd": float(cost_usd) if cost_usd is not None else None,
                "source_url": rate.get("source_url") if isinstance(rate, dict) else None,
                "as_of": rate.get("as_of") if isinstance(rate, dict) else None,
            }
        )

    def to_dict(self) -> dict[str, Any]:
        known_costs = [row["cost_usd"] for row in self._costs]
        total = sum(known_costs) if all(value is not None for value in known_costs) else None
        return {"stages": self._stages.copy(), "costs": list(self._costs), "total_cost_usd": total}
