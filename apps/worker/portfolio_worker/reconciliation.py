from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import TypeVar

Key = TypeVar("Key", bound=str)


@dataclass(frozen=True, slots=True)
class ReconciliationDifference:
    key: str
    expected: Decimal
    actual: Decimal
    difference: Decimal
    tolerance: Decimal

    @property
    def within_tolerance(self) -> bool:
        return abs(self.difference) <= self.tolerance


@dataclass(frozen=True, slots=True)
class ReconciliationResult:
    differences: tuple[ReconciliationDifference, ...]

    @property
    def matched(self) -> bool:
        return all(item.within_tolerance for item in self.differences)

    @property
    def issues(self) -> tuple[ReconciliationDifference, ...]:
        return tuple(item for item in self.differences if not item.within_tolerance)


def reconcile_balances(
    expected: dict[str, Decimal],
    actual: dict[str, Decimal],
    *,
    tolerance: Decimal,
) -> ReconciliationResult:
    if tolerance < 0:
        raise ValueError("tolerance cannot be negative")
    keys = sorted(set(expected) | set(actual))
    differences = tuple(
        ReconciliationDifference(
            key=key,
            expected=expected.get(key, Decimal(0)),
            actual=actual.get(key, Decimal(0)),
            difference=actual.get(key, Decimal(0)) - expected.get(key, Decimal(0)),
            tolerance=tolerance,
        )
        for key in keys
    )
    return ReconciliationResult(differences)
