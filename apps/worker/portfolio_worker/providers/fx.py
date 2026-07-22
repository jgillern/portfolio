from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from decimal import Decimal

import httpx
from defusedxml import ElementTree


@dataclass(frozen=True, slots=True)
class FxQuote:
    rate_date: date
    base_currency: str
    quote_currency: str
    rate: Decimal
    provider: str
    convention: str


class CnbFxProvider:
    endpoint = "https://www.cnb.cz/en/financial_markets/foreign_exchange_market/exchange_rate_fixing/daily.txt"

    def parse(self, payload: str, *, rate_date: date) -> tuple[FxQuote, ...]:
        quotes: list[FxQuote] = []
        for line in payload.splitlines():
            if "|" not in line or line.lower().startswith("country|"):
                continue
            parts = line.split("|")
            if len(parts) != 5:
                continue
            _, _, amount, code, rate = parts
            if not amount.isdigit() or len(code) != 3:
                continue
            normalized = Decimal(rate.replace(",", ".")) / Decimal(amount)
            quotes.append(
                FxQuote(
                    rate_date=rate_date,
                    base_currency=code.upper(),
                    quote_currency="CZK",
                    rate=normalized,
                    provider="CNB",
                    convention="CZK per one unit of foreign currency",
                )
            )
        if not quotes:
            raise ValueError("CNB response did not contain any rates")
        return tuple(quotes)

    def fetch(self, rate_date: date) -> tuple[FxQuote, ...]:
        response = httpx.get(
            self.endpoint,
            params={"date": rate_date.strftime("%d.%m.%Y")},
            timeout=20,
        )
        response.raise_for_status()
        return self.parse(response.text, rate_date=rate_date)


class EcbFxProvider:
    endpoint = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist-90d.xml"

    def parse(self, payload: str, *, rate_date: date) -> tuple[FxQuote, ...]:
        root = ElementTree.fromstring(payload)
        selected = None
        for element in root.iter():
            if element.attrib.get("time") == rate_date.isoformat():
                selected = element
                break
        if selected is None:
            raise ValueError("ECB response did not contain the requested date")
        quotes = [
            FxQuote(
                rate_date=rate_date,
                base_currency="EUR",
                quote_currency=element.attrib["currency"].upper(),
                rate=Decimal(element.attrib["rate"]),
                provider="ECB",
                convention="foreign currency units per EUR",
            )
            for element in selected
            if "currency" in element.attrib and "rate" in element.attrib
        ]
        if not quotes:
            raise ValueError("ECB response did not contain any rates")
        return tuple(quotes)

    def fetch(self, rate_date: date) -> tuple[FxQuote, ...]:
        response = httpx.get(self.endpoint, timeout=20)
        response.raise_for_status()
        return self.parse(response.text, rate_date=rate_date)
