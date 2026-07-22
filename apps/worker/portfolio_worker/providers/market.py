from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx


@dataclass(frozen=True, slots=True)
class PriceQuote:
    price_date: date
    close: Decimal
    currency: str
    provider: str
    symbol: str


class TwelveDataProvider:
    endpoint = "https://api.twelvedata.com/time_series"

    def parse(self, payload: dict[str, Any], *, symbol: str, currency: str) -> PriceQuote:
        if payload.get("status") == "error":
            raise ValueError("Twelve Data returned an error")
        values = payload.get("values") or []
        if not values:
            raise ValueError("Twelve Data returned no prices")
        latest = max(values, key=lambda item: item["datetime"])
        return PriceQuote(
            price_date=datetime.fromisoformat(latest["datetime"]).date(),
            close=Decimal(latest["close"]),
            currency=currency,
            provider="TWELVE_DATA",
            symbol=symbol,
        )

    def fetch(self, *, symbol: str, currency: str, api_key: str) -> PriceQuote:
        response = httpx.get(
            self.endpoint,
            params={
                "symbol": symbol,
                "interval": "1day",
                "outputsize": 5,
                "apikey": api_key,
            },
            timeout=20,
        )
        response.raise_for_status()
        return self.parse(response.json(), symbol=symbol, currency=currency)


class AlphaVantageProvider:
    endpoint = "https://www.alphavantage.co/query"

    def parse(self, payload: dict[str, Any], *, symbol: str, currency: str) -> PriceQuote:
        series = payload.get("Time Series (Daily)") or {}
        if not series:
            raise ValueError("Alpha Vantage returned no daily series")
        latest_date = max(series)
        values = series[latest_date]
        close = values.get("5. adjusted close") or values.get("4. close")
        if close is None:
            raise ValueError("Alpha Vantage response has no close")
        return PriceQuote(
            price_date=date.fromisoformat(latest_date),
            close=Decimal(close),
            currency=currency,
            provider="ALPHA_VANTAGE",
            symbol=symbol,
        )

    def fetch(self, *, symbol: str, currency: str, api_key: str) -> PriceQuote:
        response = httpx.get(
            self.endpoint,
            params={
                "function": "TIME_SERIES_DAILY_ADJUSTED",
                "symbol": symbol,
                "outputsize": "compact",
                "apikey": api_key,
            },
            timeout=20,
        )
        response.raise_for_status()
        return self.parse(response.json(), symbol=symbol, currency=currency)
