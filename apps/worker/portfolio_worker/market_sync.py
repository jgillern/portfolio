from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol

from .config import Settings
from .providers.market import (
    AlphaVantageProvider,
    PriceQuote,
    TwelveDataProvider,
)
from .repository import WorkerRepository


class MarketProvider(Protocol):
    def fetch(
        self,
        *,
        symbol: str,
        currency: str,
        api_key: str,
    ) -> PriceQuote: ...


@dataclass(frozen=True, slots=True)
class MarketSyncResult:
    imported: int
    fallback_used: int
    skipped: int
    errors: int


class MarketSync:
    def __init__(
        self,
        repository: WorkerRepository,
        settings: Settings,
        *,
        twelve_data: MarketProvider | None = None,
        alpha_vantage: MarketProvider | None = None,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._twelve_data = twelve_data or TwelveDataProvider()
        self._alpha_vantage = alpha_vantage or AlphaVantageProvider()

    def run(self) -> MarketSyncResult:
        imported = fallback_used = skipped = errors = 0
        for target in self._repository.list_price_targets():
            quote, used_fallback, was_skipped = self._fetch_target(
                target
            )
            if was_skipped:
                skipped += 1
                continue
            if quote is None:
                errors += 1
                continue
            self._repository.upsert_price_quote(
                listing_id=target["listing_id"],
                instrument_id=target["instrument_id"],
                quote=quote,
            )
            imported += 1
            fallback_used += int(used_fallback)

        self._repository.update_connector_state(
            "MARKET_DATA",
            success=errors == 0,
            imported=imported,
        )
        return MarketSyncResult(
            imported=imported,
            fallback_used=fallback_used,
            skipped=skipped,
            errors=errors,
        )

    def _fetch_target(
        self,
        target: dict[str, Any],
    ) -> tuple[PriceQuote | None, bool, bool]:
        symbols = target["provider_symbols"]
        currency = target["currency"]
        attempts: list[tuple[MarketProvider, str, str | None]] = [
            (
                self._twelve_data,
                str(symbols.get("TWELVE_DATA") or ""),
                self._settings.twelve_data_api_key,
            ),
            (
                self._alpha_vantage,
                str(symbols.get("ALPHA_VANTAGE") or ""),
                self._settings.alpha_vantage_api_key,
            ),
        ]
        configured = [
            (provider, symbol, api_key)
            for provider, symbol, api_key in attempts
            if symbol and api_key
        ]
        if not configured:
            return None, False, True
        for index, (provider, symbol, api_key) in enumerate(configured):
            try:
                return (
                    provider.fetch(
                        symbol=symbol,
                        currency=currency,
                        api_key=api_key or "",
                    ),
                    index > 0,
                    False,
                )
            except (ValueError, OSError):
                continue
        return None, len(configured) > 1, False
