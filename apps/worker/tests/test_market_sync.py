from datetime import date
from decimal import Decimal
from types import SimpleNamespace
from uuid import UUID

from portfolio_worker.market_sync import MarketSync
from portfolio_worker.providers.market import PriceQuote


class FakeRepository:
    def __init__(self) -> None:
        self.saved: list[PriceQuote] = []
        self.connector_success: bool | None = None

    def list_price_targets(self) -> list[dict]:
        return [
            {
                "listing_id": UUID("00000000-0000-4000-8000-000000000001"),
                "instrument_id": UUID("00000000-0000-4000-8000-000000000002"),
                "currency": "EUR",
                "provider_symbols": {
                    "TWELVE_DATA": "SYN:TEST",
                    "ALPHA_VANTAGE": "SYN.TEST",
                },
            }
        ]

    def upsert_price_quote(
        self,
        *,
        listing_id: UUID,
        instrument_id: UUID,
        quote: PriceQuote,
    ) -> None:
        assert listing_id
        assert instrument_id
        self.saved.append(quote)

    def update_connector_state(
        self,
        _connector: str,
        *,
        success: bool,
        imported: int,
    ) -> None:
        assert imported == 1
        self.connector_success = success


class FailingProvider:
    def fetch(self, **_kwargs) -> PriceQuote:
        raise ValueError("synthetic provider failure")


class WorkingProvider:
    def fetch(self, *, symbol: str, currency: str, api_key: str) -> PriceQuote:
        assert api_key
        return PriceQuote(
            price_date=date(2026, 7, 21),
            close=Decimal("123.45"),
            currency=currency,
            provider="ALPHA_VANTAGE",
            symbol=symbol,
        )


def test_market_sync_uses_explicit_provider_fallback() -> None:
    repository = FakeRepository()
    settings = SimpleNamespace(
        twelve_data_api_key="synthetic-twelve-key",
        alpha_vantage_api_key="synthetic-alpha-key",
    )
    result = MarketSync(
        repository,
        settings,
        twelve_data=FailingProvider(),
        alpha_vantage=WorkingProvider(),
    ).run()
    assert result.imported == 1
    assert result.fallback_used == 1
    assert repository.connector_success is True
