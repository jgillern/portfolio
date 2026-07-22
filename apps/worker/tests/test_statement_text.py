from decimal import Decimal

from portfolio_worker.models import EventType, ExecutionLegType
from portfolio_worker.parsers.statement_text import (
    GeorgePdfParser,
    XtbPdfParser,
)


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
