from decimal import Decimal

from portfolio_worker.reconciliation import reconcile_balances


def test_reconciliation_surfaces_unknown_and_out_of_tolerance_items() -> None:
    result = reconcile_balances(
        {"IE00B4L5Y983": Decimal("10"), "CASH:EUR": Decimal("50")},
        {"IE00B4L5Y983": Decimal("10.0001"), "CASH:EUR": Decimal("49"), "CASH:CZK": Decimal("5")},
        tolerance=Decimal("0.001"),
    )
    assert result.matched is False
    assert {item.key for item in result.issues} == {"CASH:CZK", "CASH:EUR"}
