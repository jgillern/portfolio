from datetime import UTC, datetime
from decimal import Decimal

import pytest

from portfolio_worker.ledger import AppendOnlyLedger, LedgerInvariantError
from portfolio_worker.models import EventType, NormalizedEvent


def buy(quantity: str = "2") -> NormalizedEvent:
    return NormalizedEvent(
        broker_code="PATRIA",
        account_ref="patria-standard",
        event_type=EventType.BUY,
        occurred_at=datetime(2026, 1, 1, tzinfo=UTC),
        instrument_name="Synthetic Equity",
        isin="US0378331005",
        quantity_delta=Decimal(quantity),
        unit_price=Decimal("10"),
        gross_amount=Decimal("-20"),
        gross_currency="USD",
    )


def test_duplicate_post_is_idempotent() -> None:
    ledger = AppendOnlyLedger()
    first, created_first = ledger.post(buy())
    second, created_second = ledger.post(buy())
    assert created_first is True
    assert created_second is False
    assert first == second
    assert len(ledger.records) == 1


def test_reversal_preserves_history_and_neutralizes_position() -> None:
    ledger = AppendOnlyLedger()
    original, _ = ledger.post(buy())
    reversal = ledger.reverse(original.id)
    assert reversal.reverses_event_id == original.id
    assert len(ledger.records) == 2
    assert ledger.position("patria-standard", "US0378331005") == 0


def test_unsupported_short_position_is_rejected() -> None:
    ledger = AppendOnlyLedger()
    sell = buy().model_copy(
        update={
            "event_type": EventType.SELL,
            "quantity_delta": Decimal("-1"),
            "gross_amount": Decimal("10"),
        }
    )
    with pytest.raises(LedgerInvariantError):
        ledger.post(sell)
