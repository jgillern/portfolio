from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass
from decimal import Decimal


@dataclass(frozen=True, slots=True)
class PositionInput:
    account_id: str
    instrument_id: str
    quantity: Decimal
    price: Decimal | None
    price_currency: str | None
    cost_basis: Decimal | None
    asset_class: str
    quality: str


@dataclass(frozen=True, slots=True)
class ValuedPosition:
    account_id: str
    instrument_id: str
    quantity: Decimal
    market_value: Decimal | None
    cost_basis: Decimal | None
    unrealized_result: Decimal | None
    reporting_currency: str
    quality: str


@dataclass(frozen=True, slots=True)
class FundHolding:
    underlying_key: str
    label: str
    weight: Decimal


@dataclass(frozen=True, slots=True)
class ExposureItem:
    key: str
    label: str
    value: Decimal
    weight: Decimal
    source: str
    coverage: Decimal


class FxBook:
    def __init__(self, rates: dict[tuple[str, str], Decimal]) -> None:
        self._graph: dict[str, list[tuple[str, Decimal]]] = defaultdict(list)
        for (base, quote), rate in rates.items():
            if rate <= 0:
                raise ValueError("FX rate must be positive")
            self._graph[base].append((quote, rate))
            self._graph[quote].append((base, Decimal(1) / rate))

    def rate(self, source: str, target: str) -> Decimal:
        if source == target:
            return Decimal(1)
        queue = deque([(source, Decimal(1))])
        visited = {source}
        while queue:
            currency, accumulated = queue.popleft()
            for neighbor, edge in self._graph.get(currency, []):
                if neighbor in visited:
                    continue
                candidate = accumulated * edge
                if neighbor == target:
                    return candidate
                visited.add(neighbor)
                queue.append((neighbor, candidate))
        raise KeyError(f"missing FX path from {source} to {target}")

    def convert(self, amount: Decimal, source: str, target: str) -> Decimal:
        return amount * self.rate(source, target)


def value_positions(
    positions: list[PositionInput],
    *,
    reporting_currency: str,
    fx: FxBook,
) -> tuple[ValuedPosition, ...]:
    output: list[ValuedPosition] = []
    for position in positions:
        market_value = None
        result = None
        quality = position.quality
        if position.price is not None and position.price_currency:
            try:
                market_value = fx.convert(
                    position.quantity * position.price,
                    position.price_currency,
                    reporting_currency,
                )
                if position.cost_basis is not None:
                    result = market_value - position.cost_basis
            except KeyError:
                quality = "missing"
        else:
            quality = "missing"
        output.append(
            ValuedPosition(
                account_id=position.account_id,
                instrument_id=position.instrument_id,
                quantity=position.quantity,
                market_value=market_value,
                cost_basis=position.cost_basis,
                unrealized_result=result,
                reporting_currency=reporting_currency,
                quality=quality,
            )
        )
    return tuple(output)


def look_through_exposure(
    values: dict[str, Decimal],
    holdings: dict[str, tuple[FundHolding, ...]],
) -> tuple[ExposureItem, ...]:
    total = sum(values.values(), Decimal(0))
    if total <= 0:
        return ()
    aggregated: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    known_value = Decimal(0)
    for instrument_id, value in values.items():
        fund_holdings = holdings.get(instrument_id)
        if not fund_holdings:
            aggregated[("direct", instrument_id)] += value
            known_value += value
            continue
        covered_weight = sum((item.weight for item in fund_holdings), Decimal(0))
        if covered_weight > 1:
            raise ValueError("fund holdings exceed 100 percent")
        for item in fund_holdings:
            aggregated[("look_through", item.underlying_key)] += value * item.weight
        known_value += value * covered_weight
        if covered_weight < 1:
            aggregated[("unknown", "Unknown")] += value * (1 - covered_weight)

    coverage = known_value / total
    labels = {
        item.underlying_key: item.label
        for items in holdings.values()
        for item in items
    }
    return tuple(
        ExposureItem(
            key=key,
            label=labels.get(key, key),
            value=value,
            weight=value / total,
            source=source,
            coverage=coverage,
        )
        for (source, key), value in sorted(aggregated.items())
    )
