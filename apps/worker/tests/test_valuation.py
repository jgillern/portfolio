from decimal import Decimal

from portfolio_worker.valuation import (
    FundHolding,
    FxBook,
    PositionInput,
    look_through_exposure,
    value_positions,
)


def test_valuation_marks_missing_fx_instead_of_returning_zero() -> None:
    valued = value_positions(
        [
            PositionInput(
                account_id="one",
                instrument_id="fund",
                quantity=Decimal("2"),
                price=Decimal("100"),
                price_currency="EUR",
                cost_basis=Decimal("180"),
                asset_class="EQUITY",
                quality="verified",
            )
        ],
        reporting_currency="CZK",
        fx=FxBook({}),
    )
    assert valued[0].market_value is None
    assert valued[0].quality == "missing"


def test_look_through_preserves_unknown_weight_and_coverage() -> None:
    exposures = look_through_exposure(
        {"fund": Decimal("100")},
        {
            "fund": (
                FundHolding("US0378331005", "Synthetic Company", Decimal("0.6")),
            )
        },
    )
    by_key = {item.key: item for item in exposures}
    assert by_key["US0378331005"].value == Decimal("60")
    assert by_key["Unknown"].value == Decimal("40")
    assert by_key["Unknown"].coverage == Decimal("0.6")
