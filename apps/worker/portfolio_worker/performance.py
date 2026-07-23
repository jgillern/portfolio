from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal, getcontext

getcontext().prec = 38


@dataclass(frozen=True, slots=True)
class TwrPeriod:
    opening_value: Decimal
    closing_value: Decimal
    external_flow: Decimal = Decimal(0)

    def return_rate(self) -> Decimal:
        if self.opening_value == 0:
            raise ValueError("opening value must be non-zero")
        return (self.closing_value - self.external_flow) / self.opening_value - Decimal(1)


def time_weighted_return(periods: list[TwrPeriod]) -> Decimal | None:
    if not periods:
        return None
    growth = Decimal(1)
    for period in periods:
        growth *= Decimal(1) + period.return_rate()
    return growth - Decimal(1)


def _xnpv(rate: Decimal, cash_flows: list[tuple[date, Decimal]]) -> Decimal:
    if rate <= Decimal(-1):
        raise ValueError("rate must be greater than -1")
    origin = cash_flows[0][0]
    return sum(
        amount / ((Decimal(1) + rate) ** (Decimal((when - origin).days) / Decimal("365")))
        for when, amount in cash_flows
    )


def xirr(
    cash_flows: list[tuple[date, Decimal]],
    *,
    tolerance: Decimal = Decimal("0.00000001"),
    max_iterations: int = 256,
) -> Decimal | None:
    if len(cash_flows) < 2:
        return None
    ordered = sorted(cash_flows, key=lambda item: item[0])
    amounts = [amount for _, amount in ordered]
    if not any(amount < 0 for amount in amounts) or not any(amount > 0 for amount in amounts):
        return None

    low = Decimal("-0.999999")
    high = Decimal("10")
    low_value = _xnpv(low, ordered)
    high_value = _xnpv(high, ordered)
    while low_value * high_value > 0 and high < Decimal("1000000"):
        high *= Decimal(10)
        high_value = _xnpv(high, ordered)
    if low_value * high_value > 0:
        return None

    for _ in range(max_iterations):
        middle = (low + high) / Decimal(2)
        value = _xnpv(middle, ordered)
        if abs(value) <= tolerance or abs(high - low) <= tolerance:
            return middle
        if low_value * value <= 0:
            high = middle
        else:
            low = middle
            low_value = value
    return (low + high) / Decimal(2)
