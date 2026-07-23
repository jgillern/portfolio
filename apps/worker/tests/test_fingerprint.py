from datetime import UTC, datetime
from decimal import Decimal

from portfolio_worker.fingerprint import economic_fingerprint, sha256_json
from portfolio_worker.models import EventType, ExecutionLegType, NormalizedEvent


def event(leg_type: ExecutionLegType) -> NormalizedEvent:
    return NormalizedEvent(
        broker_code="XTB",
        account_ref="xtb-standard",
        event_type=EventType.BUY,
        occurred_at=datetime(2026, 1, 2, 10, 30, tzinfo=UTC),
        instrument_name="Synthetic World ETF",
        isin="IE00B4L5Y983",
        quantity_delta=Decimal("1.25"),
        unit_price=Decimal("100"),
        gross_amount=Decimal("-125"),
        gross_currency="EUR",
        external_order_id="ORDER-1",
        execution_leg_type=leg_type,
    )


def test_json_fingerprint_is_order_independent() -> None:
    assert sha256_json({"b": Decimal("1.00"), "a": 2}) == sha256_json(
        {"a": 2, "b": Decimal("1")}
    )


def test_execution_leg_type_is_part_of_fingerprint() -> None:
    assert economic_fingerprint(event(ExecutionLegType.WHOLE_SHARE)) != economic_fingerprint(
        event(ExecutionLegType.FRACTIONAL_RIGHT)
    )


def test_transport_metadata_is_not_economic_identity() -> None:
    first = event(ExecutionLegType.WHOLE_SHARE)
    second = first.model_copy(update={"metadata": {"gmail_message_id": "different"}})
    assert economic_fingerprint(first) == economic_fingerprint(second)
