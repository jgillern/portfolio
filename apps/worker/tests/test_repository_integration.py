from __future__ import annotations

import os
from datetime import date, datetime, UTC
from decimal import Decimal

import psycopg
import pytest

from portfolio_worker.models import (
    CashLeg,
    CashLegType,
    EventType,
    NormalizedEvent,
)
from portfolio_worker.repository import WorkerRepository


pytestmark = pytest.mark.skipif(
    not os.environ.get("PGURL"),
    reason="PostgreSQL integration URL is not configured",
)


def event(
    event_type: EventType,
    *,
    when: datetime,
    amount: str,
    quantity: str | None = None,
    price: str | None = None,
    external: bool = False,
    fee: str | None = None,
) -> NormalizedEvent:
    legs = [
        CashLeg(
            leg_type=CashLegType.PRINCIPAL,
            currency="CZK",
            amount=Decimal(amount),
        )
    ]
    if fee is not None:
        legs.append(
            CashLeg(
                leg_type=CashLegType.FEE,
                currency="CZK",
                amount=Decimal(fee),
            )
        )
    return NormalizedEvent(
        broker_code="XTB",
        account_ref="integration",
        event_type=event_type,
        occurred_at=when,
        trade_date=when.date(),
        instrument_name=(
            "Synthetic ETF"
            if event_type in {EventType.BUY, EventType.SELL}
            else None
        ),
        isin=(
            "IE00SYNTH001"
            if event_type in {EventType.BUY, EventType.SELL}
            else None
        ),
        quantity_delta=Decimal(quantity) if quantity else None,
        unit_price=Decimal(price) if price else None,
        gross_amount=Decimal(amount),
        gross_currency="CZK",
        external_cash_flow=external,
        cash_legs=tuple(legs),
    )


def register(
    repository: WorkerRepository,
    *,
    account_id: object,
    fingerprint: str,
    received_at: datetime,
) -> object:
    import_id, created = repository.register_import(
        broker_code="XTB",
        account_id=account_id,
        source_channel="SYNTHETIC",
        document_type="integration",
        source_fingerprint=fingerprint,
        parser_version="integration-1",
        received_at=received_at,
    )
    assert created
    return import_id


def test_repository_posts_fifo_and_rebuilds_performance_snapshots() -> None:
    connection_string = os.environ["PGURL"]
    repository = WorkerRepository(connection_string)
    first_day = datetime(2026, 1, 5, 12, tzinfo=UTC)
    second_day = datetime(2026, 1, 6, 12, tzinfo=UTC)

    with psycopg.connect(connection_string) as connection:
        account_id = connection.execute(
            """
            INSERT INTO account (
              broker_id, pseudonym, tax_wrapper, base_currency
            )
            SELECT id, 'integration', 'STANDARD', 'CZK'
            FROM broker
            WHERE code = 'XTB'
            RETURNING id
            """
        ).fetchone()[0]

    first_import = register(
        repository,
        account_id=account_id,
        fingerprint="1" * 64,
        received_at=first_day,
    )
    accepted, duplicates = repository.post_batch(
        raw_import_id=first_import,
        account_id=account_id,
        events=(
            event(
                EventType.DEPOSIT,
                when=first_day,
                amount="1000",
                external=True,
            ),
            event(
                EventType.BUY,
                when=first_day,
                amount="-500",
                quantity="10",
                price="50",
                fee="-10",
            ),
        ),
    )
    assert (accepted, duplicates) == (2, 0)

    with psycopg.connect(connection_string) as connection:
        instrument_id = connection.execute(
            "SELECT id FROM instrument WHERE isin = 'IE00SYNTH001'"
        ).fetchone()[0]
        connection.execute(
            """
            INSERT INTO price (
              instrument_id, price_date, close, currency,
              provider, quality, retrieved_at
            )
            VALUES (%s, %s, 50, 'CZK', 'integration', 'VERIFIED', %s)
            """,
            (instrument_id, first_day.date(), first_day),
        )
        connection.execute(
            """
            INSERT INTO benchmark (
              code, display_name, proxy_instrument_id,
              methodology_version, valid_from
            )
            VALUES (
              'SP500', 'S&P 500 ETF proxy', %s, 'integration-1', %s
            )
            """,
            (instrument_id, first_day.date()),
        )
    repository.rebuild_position_snapshots(first_day.date(), "CZK")

    second_import = register(
        repository,
        account_id=account_id,
        fingerprint="2" * 64,
        received_at=second_day,
    )
    repository.post_batch(
        raw_import_id=second_import,
        account_id=account_id,
        events=(
            event(
                EventType.SELL,
                when=second_day,
                amount="280",
                quantity="-4",
                price="70",
                fee="-5",
            ),
        ),
    )
    with psycopg.connect(connection_string) as connection:
        connection.execute(
            """
            INSERT INTO price (
              instrument_id, price_date, close, currency,
              provider, quality, retrieved_at
            )
            VALUES (%s, %s, 70, 'CZK', 'integration', 'VERIFIED', %s)
            """,
            (instrument_id, second_day.date(), second_day),
        )
    repository.rebuild_position_snapshots(second_day.date(), "CZK")
    assert repository.rebuild_benchmark_series(second_day.date(), "CZK") == 1

    with psycopg.connect(connection_string) as connection:
        lot_row = connection.execute(
            """
            SELECT remaining_quantity
            FROM lot
            WHERE account_id = %s AND instrument_id = %s
            """,
            (account_id, instrument_id),
        ).fetchone()
        benchmark_value = connection.execute(
            """
            SELECT normalized_value
            FROM benchmark_series
            WHERE series_date = %s
              AND reporting_currency = 'CZK'
            """,
            (second_day.date(),),
        ).fetchone()[0]
        snapshot = connection.execute(
            """
            SELECT
              market_value,
              net_external_flow,
              daily_twr,
              realized_result,
              unrealized_result,
              fees
            FROM portfolio_snapshot
            WHERE snapshot_date = %s
              AND reporting_currency = 'CZK'
              AND account_id IS NULL
              AND tax_wrapper IS NULL
            """,
            (second_day.date(),),
        ).fetchone()

    assert lot_row[0] == Decimal("6")
    assert benchmark_value == Decimal("1.4")
    assert snapshot[0] == Decimal("1185")
    assert snapshot[1] == Decimal("0")
    assert snapshot[2] == pytest.approx(Decimal("195") / Decimal("990"))
    assert snapshot[3] == Decimal("71")
    assert snapshot[4] == Decimal("114")
    assert snapshot[5] == Decimal("15")
