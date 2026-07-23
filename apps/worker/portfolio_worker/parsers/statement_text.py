from __future__ import annotations

import csv
from dataclasses import dataclass
from decimal import Decimal
from io import StringIO

from portfolio_worker.models import (
    CashLeg,
    CashLegType,
    EventType,
    ExecutionLegType,
    NormalizedEvent,
)
from portfolio_worker.parsers.base import (
    ParseError,
    normalized_header,
    parse_datetime,
    parse_decimal,
)

_EVENT_ALIASES = {
    "buy": EventType.BUY,
    "nakup": EventType.BUY,
    "sell": EventType.SELL,
    "prodej": EventType.SELL,
    "deposit": EventType.DEPOSIT,
    "vklad": EventType.DEPOSIT,
    "withdrawal": EventType.WITHDRAWAL,
    "vyber": EventType.WITHDRAWAL,
    "dividend": EventType.DIVIDEND,
    "dividenda": EventType.DIVIDEND,
    "interest": EventType.INTEREST,
    "urok": EventType.INTEREST,
    "fee": EventType.FEE,
    "poplatek": EventType.FEE,
    "tax": EventType.TAX,
    "dan": EventType.TAX,
    "fx_conversion": EventType.FX_CONVERSION,
    "menova_konverze": EventType.FX_CONVERSION,
}

_LEG_ALIASES = {
    "whole_share": ExecutionLegType.WHOLE_SHARE,
    "whole": ExecutionLegType.WHOLE_SHARE,
    "cely_kus": ExecutionLegType.WHOLE_SHARE,
    "fractional_right": ExecutionLegType.FRACTIONAL_RIGHT,
    "fractional": ExecutionLegType.FRACTIONAL_RIGHT,
    "frakcni_pravo": ExecutionLegType.FRACTIONAL_RIGHT,
    "other": ExecutionLegType.OTHER,
}


@dataclass(frozen=True, slots=True)
class StatementTextParser:
    broker_code: str
    version: str

    def parse(self, text: str, *, account_ref: str) -> tuple[NormalizedEvent, ...]:
        lines = [line.strip() for line in text.splitlines() if "|" in line]
        if len(lines) < 2:
            raise ParseError("STATEMENT_TABLE_MISSING")
        reader = csv.DictReader(StringIO("\n".join(lines)), delimiter="|")
        if reader.fieldnames is None:
            raise ParseError("STATEMENT_HEADER_MISSING")
        reader.fieldnames = [normalized_header(item) for item in reader.fieldnames]
        required = {"occurred_at", "event_type", "currency", "gross"}
        if not required.issubset(reader.fieldnames):
            raise ParseError("STATEMENT_COLUMNS_MISSING")

        events = tuple(
            self._parse_row(
                {normalized_header(key): (value or "").strip() for key, value in row.items()},
                account_ref,
            )
            for row in reader
            if any((value or "").strip() for value in row.values())
        )
        if not events:
            raise ParseError("STATEMENT_EVENTS_MISSING")
        return events

    def _parse_row(self, row: dict[str, str], account_ref: str) -> NormalizedEvent:
        raw_type = normalized_header(row["event_type"])
        try:
            event_type = _EVENT_ALIASES[raw_type]
        except KeyError as exc:
            raise ParseError("STATEMENT_EVENT_UNSUPPORTED") from exc

        currency = row["currency"].upper()
        gross = parse_decimal(row["gross"])
        quantity = abs(parse_decimal(row.get("quantity", "")))
        price = abs(parse_decimal(row.get("price", "")))
        fee = abs(parse_decimal(row.get("fee", "")))
        tax = abs(parse_decimal(row.get("tax", "")))
        cash_legs: list[CashLeg] = []

        if event_type is EventType.BUY:
            gross = -abs(gross)
            quantity_delta: Decimal | None = quantity
        elif event_type is EventType.SELL:
            gross = abs(gross)
            quantity_delta = -quantity
        else:
            quantity_delta = None
            if event_type is EventType.DEPOSIT:
                gross = abs(gross)
            elif event_type is EventType.WITHDRAWAL:
                gross = -abs(gross)

        if gross:
            leg_type = {
                EventType.DIVIDEND: CashLegType.INCOME_GROSS,
                EventType.INTEREST: CashLegType.INCOME_GROSS,
                EventType.FEE: CashLegType.FEE,
                EventType.TAX: CashLegType.TAX,
            }.get(event_type, CashLegType.PRINCIPAL)
            cash_legs.append(
                CashLeg(leg_type=leg_type, currency=currency, amount=gross)
            )
        if fee:
            cash_legs.append(
                CashLeg(
                    leg_type=CashLegType.FEE,
                    currency=currency,
                    amount=-fee,
                )
            )
        if tax:
            cash_legs.append(
                CashLeg(
                    leg_type=CashLegType.TAX,
                    currency=currency,
                    amount=-tax,
                )
            )

        leg_type = None
        if event_type in {EventType.BUY, EventType.SELL}:
            raw_leg = normalized_header(row.get("leg_type") or "whole_share")
            leg_type = _LEG_ALIASES.get(raw_leg)
            if leg_type is None:
                raise ParseError("STATEMENT_LEG_UNSUPPORTED")

        occurred_at = parse_datetime(row["occurred_at"])
        isin = row.get("isin", "").upper() or None
        return NormalizedEvent(
            broker_code=self.broker_code,
            account_ref=account_ref,
            event_type=event_type,
            occurred_at=occurred_at,
            trade_date=occurred_at.date(),
            instrument_name=row.get("name") or None,
            isin=isin,
            ticker=row.get("ticker") or None,
            quantity_delta=quantity_delta,
            unit_price=price if price else None,
            gross_amount=gross,
            gross_currency=currency,
            external_cash_flow=event_type in {
                EventType.DEPOSIT,
                EventType.WITHDRAWAL,
            },
            cash_legs=tuple(cash_legs),
            external_order_id=row.get("order_id") or None,
            execution_leg_type=leg_type,
            metadata={
                "parser_version": self.version,
                "statement_source": "pdf_text",
            },
        )


class XtbPdfParser(StatementTextParser):
    def __init__(self) -> None:
        super().__init__(broker_code="XTB", version="xtb-pdf-text-v1")


class GeorgePdfParser(StatementTextParser):
    def __init__(self) -> None:
        super().__init__(broker_code="GEORGE", version="george-pdf-text-v1")
