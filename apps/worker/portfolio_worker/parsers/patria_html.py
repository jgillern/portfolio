from __future__ import annotations

from datetime import datetime
from decimal import Decimal

from bs4 import BeautifulSoup

from ..models import CashLeg, CashLegType, EventType, ExecutionLegType, NormalizedEvent
from .base import ParseError, normalized_header, parse_datetime, parse_decimal


class PatriaHtmlParser:
    version = "patria-html-v1"

    def parse(self, html: str, *, account_ref: str) -> tuple[NormalizedEvent, ...]:
        soup = BeautifulSoup(html, "html.parser")
        events: list[NormalizedEvent] = []
        for table in soup.find_all("table"):
            rows = table.find_all("tr")
            if len(rows) < 2:
                continue
            headers = [normalized_header(cell.get_text(" ", strip=True)) for cell in rows[0].find_all(["th", "td"])]
            if "isin" not in headers or not ({"smer", "side"} & set(headers)):
                continue
            for row in rows[1:]:
                values = [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
                if not values or len(values) != len(headers):
                    continue
                item = dict(zip(headers, values, strict=True))
                events.append(self._parse_row(item, account_ref))
        if not events:
            raise ParseError("no Patria trade table found")
        return tuple(events)

    def _parse_row(self, row: dict[str, str], account_ref: str) -> NormalizedEvent:
        side = (row.get("smer") or row.get("side") or "").lower()
        is_buy = side in {"nakup", "buy", "n"}
        is_sell = side in {"prodej", "sell", "p"}
        if not (is_buy or is_sell):
            raise ParseError("unsupported Patria direction")

        quantity = abs(parse_decimal(row.get("pocet") or row.get("quantity") or "0"))
        price = abs(parse_decimal(row.get("cena") or row.get("price") or "0"))
        total = abs(parse_decimal(row.get("celkova_cena") or row.get("total") or str(quantity * price)))
        commission = abs(parse_decimal(row.get("provize") or "0"))
        market_fee = abs(parse_decimal(row.get("poplatek_trhu") or "0"))
        currency = (row.get("mena") or row.get("currency") or "").upper()
        occurred_at = parse_datetime(row.get("datum_obchodu") or row.get("executed_at") or "")
        settlement_raw = row.get("datum_vyporadani")
        settlement_date = None
        if settlement_raw:
            settlement_date = datetime.strptime(settlement_raw, "%d.%m.%Y").date()

        principal = -total if is_buy else total
        legs = [CashLeg(leg_type=CashLegType.PRINCIPAL, currency=currency, amount=principal)]
        if commission:
            legs.append(CashLeg(leg_type=CashLegType.FEE, currency=currency, amount=-commission))
        if market_fee:
            legs.append(CashLeg(leg_type=CashLegType.FEE, currency=currency, amount=-market_fee))

        return NormalizedEvent(
            broker_code="PATRIA",
            account_ref=account_ref,
            event_type=EventType.BUY if is_buy else EventType.SELL,
            occurred_at=occurred_at,
            trade_date=occurred_at.date(),
            settlement_date=settlement_date,
            instrument_name=row.get("nazev") or row.get("instrument"),
            isin=(row.get("isin") or "").upper(),
            ticker=row.get("ticker") or None,
            quantity_delta=quantity if is_buy else -quantity,
            unit_price=price,
            gross_amount=principal,
            gross_currency=currency,
            cash_legs=tuple(legs),
            external_order_id=row.get("pokyn") or row.get("order_id"),
            execution_leg_type=ExecutionLegType.WHOLE_SHARE,
            metadata={"parser_version": self.version, "market": row.get("trh")},
        )
