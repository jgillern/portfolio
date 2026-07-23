from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from uuid import UUID, uuid4

from .fingerprint import economic_fingerprint
from .models import CashLeg, EventType, NormalizedEvent


class LedgerInvariantError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class LedgerRecord:
    id: UUID
    source_fingerprint: str
    event: NormalizedEvent
    reverses_event_id: UUID | None = None


class AppendOnlyLedger:
    def __init__(self) -> None:
        self._records: list[LedgerRecord] = []
        self._by_fingerprint: dict[str, LedgerRecord] = {}
        self._reversed: set[UUID] = set()

    @property
    def records(self) -> tuple[LedgerRecord, ...]:
        return tuple(self._records)

    def position(self, account_ref: str, isin: str) -> Decimal:
        return sum(
            (
                record.event.quantity_delta or Decimal(0)
                for record in self._records
                if record.event.account_ref == account_ref and record.event.isin == isin
            ),
            Decimal(0),
        )

    def post(
        self,
        event: NormalizedEvent,
        *,
        fingerprint: str | None = None,
        reverses_event_id: UUID | None = None,
    ) -> tuple[LedgerRecord, bool]:
        resolved_fingerprint = fingerprint or economic_fingerprint(event)
        existing = self._by_fingerprint.get(resolved_fingerprint)
        if existing is not None:
            return existing, False

        if reverses_event_id is not None:
            if reverses_event_id in self._reversed:
                raise LedgerInvariantError("event has already been reversed")
            if not any(record.id == reverses_event_id for record in self._records):
                raise LedgerInvariantError("reversed event does not exist")

        if event.quantity_delta and event.isin:
            resulting = self.position(event.account_ref, event.isin) + event.quantity_delta
            if resulting < 0 and not bool(event.metadata.get("allow_short")):
                raise LedgerInvariantError("posting would create an unsupported short position")

        record = LedgerRecord(
            id=uuid4(),
            source_fingerprint=resolved_fingerprint,
            event=event,
            reverses_event_id=reverses_event_id,
        )
        self._records.append(record)
        self._by_fingerprint[resolved_fingerprint] = record
        if reverses_event_id is not None:
            self._reversed.add(reverses_event_id)
        return record, True

    def reverse(self, event_id: UUID, *, occurred_at=None) -> LedgerRecord:
        original = next((record for record in self._records if record.id == event_id), None)
        if original is None:
            raise LedgerInvariantError("event does not exist")
        if event_id in self._reversed:
            raise LedgerInvariantError("event has already been reversed")

        event = original.event
        reverse_event = NormalizedEvent(
            broker_code=event.broker_code,
            account_ref=event.account_ref,
            event_type=EventType.ADJUSTMENT_REVERSAL,
            occurred_at=occurred_at or event.occurred_at,
            trade_date=event.trade_date,
            settlement_date=event.settlement_date,
            instrument_name=event.instrument_name,
            isin=event.isin,
            ticker=event.ticker,
            quantity_delta=-event.quantity_delta if event.quantity_delta is not None else None,
            unit_price=event.unit_price,
            gross_amount=-event.gross_amount if event.gross_amount is not None else None,
            gross_currency=event.gross_currency,
            external_cash_flow=event.external_cash_flow,
            cash_legs=tuple(
                CashLeg(
                    leg_type=leg.leg_type,
                    currency=leg.currency,
                    amount=-leg.amount,
                    broker_fx_rate=leg.broker_fx_rate,
                )
                for leg in event.cash_legs
            ),
            external_order_id=event.external_order_id,
            execution_leg_type=event.execution_leg_type,
            metadata={"reverses_event_id": str(event_id)},
        )
        record, _ = self.post(reverse_event, reverses_event_id=event_id)
        return record
