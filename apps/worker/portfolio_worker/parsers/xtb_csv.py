from __future__ import annotations

import csv
import io

from ..models import CashLeg, CashLegType, EventType, ExecutionLegType, NormalizedEvent
from .base import ParseError, normalized_header, parse_datetime, parse_decimal


class XtbCsvParser:
    version = "xtb-csv-v1"

    def parse(self, payload: str, *, account_ref: str) -> tuple[NormalizedEvent, ...]:
        sample = payload[:4096]
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=",;\t")
        except csv.Error:
            dialect = csv.excel
        reader = csv.DictReader(io.StringIO(payload), dialect=dialect)
        if reader.fieldnames is None:
            raise ParseError("XTB CSV has no header")
        reader.fieldnames = [normalized_header(value) for value in reader.fieldnames]

        events: list[NormalizedEvent] = []
        for raw in reader:
            row = {
                normalized_header(key): (value or "").strip()
                for key, value in raw.items()
            }
            if not any(row.values()):
                continue
            events.append(self._parse_row(row, account_ref))
        if not events:
            raise ParseError("XTB CSV has no transactions")
        return tuple(events)

    def _parse_row(self, row: dict[str, str], account_ref: str) -> NormalizedEvent:
        side = (row.get("side") or row.get("typ") or row.get("smer") or "").lower()
        is_buy = side in {"buy", "nakup", "n"}
        is_sell = side in {"sell", "prodej", "p"}
        if not (is_buy or is_sell):
            raise ParseError("unsupported XTB direction")

        leg_raw = (row.get("leg_type") or row.get("pravni_forma") or "").lower()
        leg_type = (
            ExecutionLegType.FRACTIONAL_RIGHT
            if "fraction" in leg_raw or "frakc" in leg_raw
            else ExecutionLegType.WHOLE_SHARE
        )
        quantity = abs(parse_decimal(row.get("quantity") or row.get("objem") or "0"))
        price = abs(parse_decimal(row.get("price") or row.get("cena") or "0"))
        total_value = row.get("total") or row.get("celkova_cena") or str(quantity * price)
        total = abs(parse_decimal(total_value))
        commission = abs(
            parse_decimal(row.get("commission") or row.get("provize") or "0")
        )
        currency = (row.get("currency") or row.get("mena") or "").upper()
        occurred_at = parse_datetime(
            row.get("executed_at")
            or row.get("datum_a_cas")
            or row.get("datum")
            or ""
        )
        principal = -total if is_buy else total
        legs = [
            CashLeg(
                leg_type=CashLegType.PRINCIPAL,
                currency=currency,
                amount=principal,
            )
        ]
        if commission:
            legs.append(
                CashLeg(
                    leg_type=CashLegType.FEE,
                    currency=currency,
                    amount=-commission,
                )
            )

        return NormalizedEvent(
            broker_code="XTB",
            account_ref=account_ref,
            event_type=EventType.BUY if is_buy else EventType.SELL,
            occurred_at=occurred_at,
            trade_date=occurred_at.date(),
            instrument_name=row.get("name") or row.get("nazev"),
            isin=(row.get("isin") or "").upper() or None,
            ticker=row.get("symbol") or row.get("ticker") or None,
            quantity_delta=quantity if is_buy else -quantity,
            unit_price=price,
            gross_amount=principal,
            gross_currency=currency,
            cash_legs=tuple(legs),
            external_order_id=row.get("order_id") or row.get("cislo_pokynu") or None,
            execution_leg_type=leg_type,
            metadata={
                "parser_version": self.version,
                "symbol": row.get("symbol"),
                "venue": row.get("venue") or row.get("system_provedeni"),
            },
        )
