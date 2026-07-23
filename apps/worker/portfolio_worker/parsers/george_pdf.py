from __future__ import annotations

import re
from datetime import date
from decimal import Decimal

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
from portfolio_worker.parsers.statement_text import StatementTextParser

_ISIN = re.compile(r"\b[A-Z]{2}[A-Z0-9]{9}[0-9]\b")
_DATE_TIME = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\s+\d{2}:\d{2}(?::\d{2})?\b")
_DATE_ONLY = re.compile(r"^\s*(\d{2}\.\d{2}\.\d{4})\b")
_NUMBER = re.compile(r"(?<![A-Z0-9])-?\d+(?:[.,]\d+)?(?![A-Z0-9])")
_ORDER_VENUE = re.compile(r"^\s*(\d{6,})\s+([A-Z0-9]{3,12})\b(.*)$")


def _line(value: str) -> str:
    return " ".join(value.replace("\u00a0", " ").split())


def _numbers(value: str) -> list[Decimal]:
    return [parse_decimal(match.group(0)) for match in _NUMBER.finditer(value)]


def _date(value: str) -> date:
    day, month, year = value.split(".")
    return date(int(year), int(month), int(day))


class GeorgePdfParser:
    version = "george-pdf-text-v2"

    def parse(self, text: str, *, account_ref: str) -> tuple[NormalizedEvent, ...]:
        # Keep the synthetic pipe format as a small deterministic contract fixture.
        if "|" in text:
            return StatementTextParser(
                broker_code="GEORGE",
                version=self.version,
            ).parse(text, account_ref=account_ref)
        return self._parse_trade_overview(text, account_ref=account_ref)

    def _parse_trade_overview(
        self,
        text: str,
        *,
        account_ref: str,
    ) -> tuple[NormalizedEvent, ...]:
        lines = tuple(_line(item) for item in text.splitlines() if _line(item))
        normalized = tuple(normalized_header(item) for item in lines)
        completed_start = next(
            (
                index
                for index, item in enumerate(normalized)
                if "provedene_pokyny_a_transakce" in item
                and "dosud_neprovedene" not in item
            ),
            None,
        )
        if completed_start is None:
            raise ParseError("GEORGE_COMPLETED_SECTION_MISSING")
        pending_start = next(
            (
                index
                for index, item in enumerate(normalized)
                if index > completed_start
                and "podane_a_dosud_neprovedene" in item
            ),
            len(lines),
        )
        completed = lines[completed_start + 1 : pending_start]
        pending = lines[pending_start + 1 :] if pending_start < len(lines) else ()
        pending_count = sum(len(_ISIN.findall(item)) for item in pending)

        events: list[NormalizedEvent] = []
        for index, item in enumerate(completed):
            isin_match = _ISIN.search(item)
            if isin_match is None:
                continue
            events.append(
                self._parse_completed_trade(
                    completed,
                    index=index,
                    isin=isin_match.group(0),
                    account_ref=account_ref,
                    pending_count=pending_count,
                )
            )
        if not events:
            raise ParseError("GEORGE_COMPLETED_TRADES_MISSING")
        return tuple(events)

    def _parse_completed_trade(
        self,
        lines: tuple[str, ...],
        *,
        index: int,
        isin: str,
        account_ref: str,
        pending_count: int,
    ) -> NormalizedEvent:
        action_index = next(
            (
                candidate
                for candidate in range(max(0, index - 2), min(len(lines), index + 3))
                if "nakup_cp" in normalized_header(lines[candidate])
                or "prodej_cp" in normalized_header(lines[candidate])
            ),
            None,
        )
        if action_index is None:
            raise ParseError("GEORGE_TRADE_SIDE_MISSING")
        action = lines[action_index]
        action_normalized = normalized_header(action)
        event_type = (
            EventType.BUY if "nakup_cp" in action_normalized else EventType.SELL
        )
        isin_position = action.find(isin)
        action_numbers = _numbers(
            action[isin_position + len(isin) :] if isin_position >= 0 else action
        )
        if not action_numbers:
            raise ParseError("GEORGE_TRADE_PRICE_MISSING")
        unit_price = abs(action_numbers[0])

        submitted_line = next(
            (
                lines[candidate]
                for candidate in range(action_index - 1, max(-1, action_index - 5), -1)
                if _DATE_TIME.search(lines[candidate])
            ),
            None,
        )
        if submitted_line is None:
            raise ParseError("GEORGE_ORDER_DATE_MISSING")
        submitted_match = _DATE_TIME.search(submitted_line)
        assert submitted_match is not None
        submitted_at = parse_datetime(submitted_match.group(0))
        submitted_tail = submitted_line[submitted_match.end() :]
        submitted_number_matches = list(_NUMBER.finditer(submitted_tail))
        if len(submitted_number_matches) < 2:
            raise ParseError("GEORGE_TRADE_QUANTITY_MISSING")
        quantity = abs(parse_decimal(submitted_number_matches[-2].group(0)))
        acquisition_total = abs(parse_decimal(submitted_number_matches[-1].group(0)))
        instrument_name = submitted_tail[: submitted_number_matches[-2].start()].strip()
        if not instrument_name or quantity == 0:
            raise ParseError("GEORGE_TRADE_IDENTITY_MISSING")

        executed_at = submitted_at
        currency = None
        settlement_date = None
        external_order_id = None
        venue = None
        fee = Decimal(0)
        for candidate in range(action_index + 1, min(len(lines), action_index + 7)):
            current = lines[candidate]
            executed_match = _DATE_TIME.search(current)
            if executed_match is not None:
                executed_at = parse_datetime(executed_match.group(0))
                suffix = current[executed_match.end() :]
                currency_match = re.search(r"\b[A-Z]{3}\b", suffix)
                if currency_match is not None:
                    currency = currency_match.group(0)
                continue
            settlement_match = _DATE_ONLY.match(current)
            if settlement_match is not None and settlement_date is None:
                settlement_date = _date(settlement_match.group(1))
                continue
            order_match = _ORDER_VENUE.match(current)
            if order_match is not None:
                external_order_id = order_match.group(1)
                venue = order_match.group(2)
                order_numbers = _numbers(order_match.group(3))
                if order_numbers:
                    fee = abs(order_numbers[-1])

        if currency is None:
            currency = next(
                (
                    match.group(0)
                    for current in lines[max(0, action_index - 2) : action_index + 7]
                    if (match := re.search(r"\b[A-Z]{3}\b", current)) is not None
                ),
                None,
            )
        if currency is None:
            raise ParseError("GEORGE_TRADE_CURRENCY_MISSING")

        principal = unit_price * quantity
        signed_principal = (
            -abs(principal) if event_type is EventType.BUY else abs(principal)
        )
        signed_quantity = quantity if event_type is EventType.BUY else -quantity
        cash_legs = [
            CashLeg(
                leg_type=CashLegType.PRINCIPAL,
                currency=currency,
                amount=signed_principal,
            )
        ]
        if fee:
            cash_legs.append(
                CashLeg(
                    leg_type=CashLegType.FEE,
                    currency=currency,
                    amount=-fee,
                )
            )

        return NormalizedEvent(
            broker_code="GEORGE",
            account_ref=account_ref,
            event_type=event_type,
            occurred_at=executed_at,
            trade_date=executed_at.date(),
            settlement_date=settlement_date,
            instrument_name=instrument_name,
            isin=isin,
            quantity_delta=signed_quantity,
            unit_price=unit_price,
            gross_amount=signed_principal,
            gross_currency=currency,
            cash_legs=tuple(cash_legs),
            external_order_id=external_order_id,
            execution_leg_type=ExecutionLegType.WHOLE_SHARE,
            metadata={
                "parser_version": self.version,
                "statement_source": "ceska_sporitelna_trade_overview",
                "order_submitted_at": submitted_at.isoformat(),
                "acquisition_total_after_discount": str(acquisition_total),
                "venue": venue,
                "pending_orders_ignored": pending_count,
            },
        )
