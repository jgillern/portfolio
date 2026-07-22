from datetime import date
from decimal import Decimal

from portfolio_worker.providers.fx import CnbFxProvider, EcbFxProvider
from portfolio_worker.valuation import FxBook


def test_cnb_parser_handles_unit_multipliers_and_decimal_commas() -> None:
    payload = """22 Jul 2026 #140
Country|Currency|Amount|Code|Rate
EMU|euro|1|EUR|24,650
Japan|yen|100|JPY|15,300
"""
    quotes = CnbFxProvider().parse(payload, rate_date=date(2026, 7, 22))
    rates = {(item.base_currency, item.quote_currency): item.rate for item in quotes}
    assert rates[("EUR", "CZK")] == Decimal("24.650")
    assert rates[("JPY", "CZK")] == Decimal("0.153")


def test_ecb_parser_and_cross_currency_graph() -> None:
    payload = """<Envelope><Cube><Cube time="2026-07-22">
<Cube currency="USD" rate="1.20"/><Cube currency="CZK" rate="24.60"/>
</Cube></Cube></Envelope>"""
    quotes = EcbFxProvider().parse(payload, rate_date=date(2026, 7, 22))
    book = FxBook(
        {(quote.base_currency, quote.quote_currency): quote.rate for quote in quotes}
    )
    assert book.convert(Decimal("120"), "USD", "CZK") == Decimal("2460")
