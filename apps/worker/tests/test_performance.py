from datetime import date
from decimal import Decimal

from portfolio_worker.performance import TwrPeriod, time_weighted_return, xirr


def test_time_weighted_return_chains_subperiods() -> None:
    result = time_weighted_return(
        [
            TwrPeriod(Decimal("100"), Decimal("110")),
            TwrPeriod(Decimal("110"), Decimal("132")),
        ]
    )
    assert result == Decimal("0.32")


def test_external_flow_is_removed_from_period_return() -> None:
    result = time_weighted_return(
        [TwrPeriod(Decimal("100"), Decimal("160"), external_flow=Decimal("50"))]
    )
    assert result == Decimal("0.1")


def test_xirr_for_one_year_double_is_about_100_percent() -> None:
    result = xirr(
        [
            (date(2025, 1, 1), Decimal("-100")),
            (date(2026, 1, 1), Decimal("200")),
        ]
    )
    assert result is not None
    assert abs(result - Decimal("1")) < Decimal("0.000001")
