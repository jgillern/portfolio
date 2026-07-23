from decimal import Decimal

from portfolio_worker.providers.market import AlphaVantageProvider, TwelveDataProvider


def test_twelve_data_selects_latest_close() -> None:
    quote = TwelveDataProvider().parse(
        {
            "values": [
                {"datetime": "2026-07-21", "close": "99.5"},
                {"datetime": "2026-07-22", "close": "100.25"},
            ]
        },
        symbol="SXR8:XETR",
        currency="EUR",
    )
    assert quote.close == Decimal("100.25")


def test_alpha_vantage_prefers_adjusted_close() -> None:
    quote = AlphaVantageProvider().parse(
        {
            "Time Series (Daily)": {
                "2026-07-22": {
                    "4. close": "99",
                    "5. adjusted close": "100",
                }
            }
        },
        symbol="SXR8.DEX",
        currency="EUR",
    )
    assert quote.close == Decimal("100")
