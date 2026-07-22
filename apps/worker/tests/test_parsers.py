from decimal import Decimal
from pathlib import Path

from portfolio_worker.fingerprint import economic_fingerprint
from portfolio_worker.models import ExecutionLegType
from portfolio_worker.parsers import PatriaHtmlParser, XtbCsvParser

FIXTURES = Path(__file__).parents[3] / "tests" / "fixtures-synthetic"


def test_patria_html_with_two_trades_creates_two_events_and_fee_legs() -> None:
    events = PatriaHtmlParser().parse(
        (FIXTURES / "patria" / "trades.html").read_text(encoding="utf-8"),
        account_ref="patria-standard",
    )
    assert len(events) == 2
    assert sum(len(event.cash_legs) for event in events) == 5
    assert events[0].quantity_delta == Decimal("2")


def test_xtb_whole_and_fractional_legs_are_not_duplicates() -> None:
    events = XtbCsvParser().parse(
        (FIXTURES / "xtb" / "history.csv").read_text(encoding="utf-8"),
        account_ref="xtb-dip",
    )
    assert len(events) == 2
    assert events[0].external_order_id == events[1].external_order_id
    assert {event.execution_leg_type for event in events} == {
        ExecutionLegType.WHOLE_SHARE,
        ExecutionLegType.FRACTIONAL_RIGHT,
    }
    assert economic_fingerprint(events[0]) != economic_fingerprint(events[1])
