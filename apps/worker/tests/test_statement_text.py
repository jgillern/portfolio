from decimal import Decimal

from portfolio_worker.models import EventType, ExecutionLegType
from portfolio_worker.parsers import GeorgePdfParser
from portfolio_worker.parsers.statement_text import XtbPdfParser

HEADER = (
    "Order ID|Occurred At|Event Type|Name|ISIN|Ticker|Quantity|"
    "Price|Gross|Currency|Leg Type|Fee|Tax"
)


def test_xtb_pdf_text_keeps_whole_and_fractional_execution_legs() -> None:
    text = "\n".join(
        (
            HEADER,
            (
                "order-1|2026-01-02 10:30:00|Buy|Synthetic ETF|"
                "IE00SYNTH001|SYN|1|100|100|EUR|Whole share|1|0"
            ),
            (
                "order-1|2026-01-02 10:30:00|Buy|Synthetic ETF|"
                "IE00SYNTH001|SYN|0.25|100|25|EUR|Fractional right|0|0"
            ),
        )
    )
    events = XtbPdfParser().parse(text, account_ref="xtb-standard")
    assert len(events) == 2
    assert events[0].external_order_id == events[1].external_order_id
    assert events[0].execution_leg_type is ExecutionLegType.WHOLE_SHARE
    assert events[1].execution_leg_type is ExecutionLegType.FRACTIONAL_RIGHT
    assert events[1].quantity_delta == Decimal("0.25")


def test_george_pdf_text_marks_deposit_as_external_flow() -> None:
    text = "\n".join(
        (
            HEADER,
            (
                "cash-1|2026-01-03 09:00:00|Vklad|||||"
                "|10000|CZK|||"
            ),
        )
    )
    event = GeorgePdfParser().parse(text, account_ref="george-dip")[0]
    assert event.event_type is EventType.DEPOSIT
    assert event.external_cash_flow
    assert event.gross_amount == Decimal("10000")


def test_george_trade_overview_posts_only_completed_orders() -> None:
    text = """
Přehled obchodů
Výpis z majetkového účtu
CENNÉ PAPÍRY OBCHODOVANÉ NA BURZÁCH A JINÝCH TRZÍCH - Provedené pokyny a transakce
Podání pokynu/Valuta Název Počet CP Objem obchodu v měně obchodu
18.07.2026 16:10:56 SYNTHCZ 1 901.14
Nákup CP/Limit CZ0000000001 898.00 0.00
20.07.2026 09:00:07 CZK k 898.00
22.07.2026 0.00 0.00
106000001 BCPP 0.00 3.14
CENNÉ PAPÍRY OBCHODOVANÉ NA BURZÁCH A JINÝCH TRZÍCH - Podané a dosud neprovedené pokyny a transakce
22.07.2026 00:18:01 SYNTHCZ 1 0.00
Nákup CP/Limit CZ0000000001 900.00 0.00
106000002 CZK 0.00 19.10.2026
"""
    events = GeorgePdfParser().parse(text, account_ref="george-dip")
    assert len(events) == 1
    event = events[0]
    assert event.event_type is EventType.BUY
    assert event.external_order_id == "106000001"
    assert event.quantity_delta == Decimal("1")
    assert event.unit_price == Decimal("898.00")
    assert event.gross_amount == Decimal("-898.00")
    assert event.settlement_date.isoformat() == "2026-07-22"
    assert event.metadata["pending_orders_ignored"] == 1
    assert event.cash_legs[-1].leg_type is ExecutionLegType.__mro__[1] if False else event.cash_legs[-1].leg_type
    assert event.cash_legs[-1].amount == Decimal("-3.14")
