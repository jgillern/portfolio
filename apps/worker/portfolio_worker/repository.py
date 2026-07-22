from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from decimal import Decimal
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .crypto import SecretEnvelope
from .fingerprint import economic_fingerprint, sha256_json
from .lots import InsufficientPosition, OpenLot, allocate_fifo
from .models import EventType, NormalizedEvent
from .performance import xirr


class RepositoryError(RuntimeError):
    pass


class WorkerRepository:
    def __init__(self, connection_string: str) -> None:
        self._connection_string = connection_string

    @contextmanager
    def connection(self) -> Iterator[Connection[Any]]:
        with psycopg.connect(self._connection_string) as connection:
            yield connection

    def resolve_account(self, broker_code: str, account_ref: str) -> UUID:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT a.id
                FROM account a
                JOIN broker b ON b.id = a.broker_id
                WHERE b.code = %s AND a.pseudonym = %s
                """,
                (broker_code, account_ref),
            ).fetchone()
        if row is None:
            raise RepositoryError("configured account was not found")
        return row[0]

    def register_import(
        self,
        *,
        broker_code: str,
        account_id: UUID,
        source_channel: str,
        document_type: str,
        source_fingerprint: str,
        parser_version: str,
        received_at: datetime,
        gmail_message_id: str | None = None,
        mime_part_id: str | None = None,
        encrypted_blob_key: str | None = None,
    ) -> tuple[UUID, bool]:
        with self.connection() as connection:
            row = connection.execute(
                """
                INSERT INTO raw_import (
                  broker_id, account_id, source_channel, document_type,
                  gmail_message_id, mime_part_id, source_fingerprint,
                  encrypted_blob_key, parser_version, received_at
                )
                SELECT
                  b.id, %s, %s, %s, %s, %s, %s, %s, %s, %s
                FROM broker b
                WHERE b.code = %s
                ON CONFLICT (source_fingerprint) DO NOTHING
                RETURNING id
                """,
                (
                    account_id,
                    source_channel,
                    document_type,
                    gmail_message_id,
                    mime_part_id,
                    source_fingerprint,
                    encrypted_blob_key,
                    parser_version,
                    received_at,
                    broker_code,
                ),
            ).fetchone()
            if row is not None:
                return row[0], True
            existing = connection.execute(
                "SELECT id FROM raw_import WHERE source_fingerprint = %s",
                (source_fingerprint,),
            ).fetchone()
            if existing is None:
                raise RepositoryError("broker does not exist")
            return existing[0], False

    def _ensure_instrument(
        self,
        connection: Connection[Any],
        event: NormalizedEvent,
    ) -> UUID | None:
        if event.isin is None and event.instrument_name is None:
            return None
        if event.isin is not None:
            existing = connection.execute(
                "SELECT id FROM instrument WHERE isin = %s",
                (event.isin,),
            ).fetchone()
            if existing is not None:
                return existing[0]
        row = connection.execute(
            """
            INSERT INTO instrument (isin, name, legal_type, asset_class, metadata)
            VALUES (%s, %s, 'OTHER', 'OTHER', %s)
            RETURNING id
            """,
            (
                event.isin,
                event.instrument_name or event.isin,
                Jsonb({"mapping_status": "unconfirmed"}),
            ),
        ).fetchone()
        if row is None:
            raise RepositoryError("failed to create instrument")
        return row[0]

    def post_batch(
        self,
        *,
        raw_import_id: UUID,
        account_id: UUID,
        events: tuple[NormalizedEvent, ...],
    ) -> tuple[int, int]:
        accepted = 0
        duplicates = 0
        with self.connection() as connection:
            connection.execute(
                "SELECT pg_advisory_xact_lock(hashtext(%s))",
                (str(account_id),),
            )
            for event in events:
                event_fingerprint = economic_fingerprint(event)
                instrument_id = self._ensure_instrument(connection, event)
                execution_leg_id = None
                if event.external_order_id and event.execution_leg_type and instrument_id:
                    order_row = connection.execute(
                        """
                        INSERT INTO broker_order (
                          account_id, raw_import_id, external_order_id,
                          executed_at, side
                        )
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (account_id, raw_import_id, external_order_id)
                        WHERE external_order_id IS NOT NULL
                        DO UPDATE SET executed_at = EXCLUDED.executed_at
                        RETURNING id
                        """,
                        (
                            account_id,
                            raw_import_id,
                            event.external_order_id,
                            event.occurred_at,
                            event.event_type.value,
                        ),
                    ).fetchone()
                    if order_row is None:
                        raise RepositoryError("failed to create broker order")
                    leg_fingerprint = sha256_json(
                        {
                            "account_id": account_id,
                            "order": event.external_order_id,
                            "leg_type": event.execution_leg_type,
                            "isin": event.isin,
                            "ticker": event.ticker,
                            "quantity": abs(event.quantity_delta or 0),
                            "price": event.unit_price,
                            "executed_at": event.occurred_at,
                        }
                    )
                    leg_row = connection.execute(
                        """
                        INSERT INTO execution_leg (
                          broker_order_id, instrument_id, leg_type, quantity,
                          price, price_currency, executed_at, venue,
                          fee_amount, source_fingerprint
                        )
                        VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                        ON CONFLICT (source_fingerprint)
                        DO UPDATE SET source_fingerprint = EXCLUDED.source_fingerprint
                        RETURNING id
                        """,
                        (
                            order_row[0],
                            instrument_id,
                            event.execution_leg_type.value,
                            abs(event.quantity_delta or 0),
                            event.unit_price or 0,
                            event.gross_currency,
                            event.occurred_at,
                            event.metadata.get("venue"),
                            abs(
                                sum(
                                    leg.amount
                                    for leg in event.cash_legs
                                    if leg.leg_type.value == "FEE"
                                )
                            ),
                            leg_fingerprint,
                        ),
                    ).fetchone()
                    execution_leg_id = leg_row[0] if leg_row else None

                event_row = connection.execute(
                    """
                    INSERT INTO ledger_event (
                      account_id, instrument_id, raw_import_id, execution_leg_id,
                      event_type, occurred_at, trade_date, settlement_date,
                      quantity_delta, unit_price, gross_amount, gross_currency,
                      external_cash_flow, source_fingerprint, metadata
                    )
                    VALUES (
                      %s, %s, %s, %s, %s, %s, %s, %s,
                      %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (source_fingerprint) DO NOTHING
                    RETURNING id
                    """,
                    (
                        account_id,
                        instrument_id,
                        raw_import_id,
                        execution_leg_id,
                        event.event_type.value,
                        event.occurred_at,
                        event.trade_date,
                        event.settlement_date,
                        event.quantity_delta,
                        event.unit_price,
                        event.gross_amount,
                        event.gross_currency,
                        event.external_cash_flow,
                        event_fingerprint,
                        Jsonb(event.metadata),
                    ),
                ).fetchone()
                if event_row is None:
                    duplicates += 1
                    continue
                accepted += 1
                for index, leg in enumerate(event.cash_legs):
                    connection.execute(
                        """
                        INSERT INTO cash_leg (
                          ledger_event_id, leg_type, currency, amount,
                          broker_fx_rate, source_fingerprint
                        )
                        VALUES (%s, %s, %s, %s, %s, %s)
                        """,
                        (
                            event_row[0],
                            leg.leg_type.value,
                            leg.currency,
                            leg.amount,
                            leg.broker_fx_rate,
                            sha256_json(
                                {
                                    "event": event_fingerprint,
                                    "index": index,
                                    "leg": leg.model_dump(mode="python"),
                                }
                            ),
                        ),
                    )
                self._update_lots(
                    connection,
                    account_id=account_id,
                    instrument_id=instrument_id,
                    event=event,
                    event_id=event_row[0],
                )
            connection.execute(
                """
                UPDATE raw_import
                SET status = 'POSTED',
                    found_count = %s,
                    accepted_count = %s,
                    rejected_count = %s
                WHERE id = %s
                """,
                (len(events), accepted, duplicates, raw_import_id),
            )
        return accepted, duplicates

    def _update_lots(
        self,
        connection: Connection[Any],
        *,
        account_id: UUID,
        instrument_id: UUID | None,
        event: NormalizedEvent,
        event_id: UUID,
    ) -> None:
        if event.event_type not in {EventType.BUY, EventType.SELL}:
            return
        if instrument_id is None or event.quantity_delta is None:
            raise RepositoryError("trade is missing an instrument or quantity")
        if event.gross_currency is None:
            raise RepositoryError("trade is missing its gross currency")

        if event.event_type is EventType.BUY:
            if event.quantity_delta <= 0:
                raise RepositoryError("buy quantity must be positive")
            principal = event.gross_amount
            if principal is None:
                if event.unit_price is None:
                    raise RepositoryError("buy is missing gross amount and unit price")
                principal = event.quantity_delta * event.unit_price
            charges = sum(
                (
                    abs(leg.amount)
                    for leg in event.cash_legs
                    if leg.leg_type.value in {"FEE", "TAX"}
                ),
                Decimal("0"),
            )
            connection.execute(
                """
                INSERT INTO lot (
                  account_id, instrument_id, opening_event_id, opened_at,
                  original_quantity, remaining_quantity, acquisition_cost,
                  cost_currency
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s)
                """,
                (
                    account_id,
                    instrument_id,
                    event_id,
                    event.occurred_at,
                    event.quantity_delta,
                    event.quantity_delta,
                    abs(principal) + charges,
                    event.gross_currency,
                ),
            )
            return

        if event.quantity_delta >= 0:
            raise RepositoryError("sell quantity must be negative")
        rows = connection.execute(
            """
            SELECT id, original_quantity, remaining_quantity, acquisition_cost
            FROM lot
            WHERE account_id = %s
              AND instrument_id = %s
              AND remaining_quantity > 0
            ORDER BY opened_at, created_at, id
            FOR UPDATE
            """,
            (account_id, instrument_id),
        ).fetchall()
        lots = tuple(
            OpenLot(
                id=row[0],
                original_quantity=row[1],
                remaining_quantity=row[2],
                acquisition_cost=row[3],
            )
            for row in rows
        )
        try:
            allocations = allocate_fifo(lots, abs(event.quantity_delta))
        except InsufficientPosition as error:
            raise RepositoryError(
                "sell exceeds the FIFO position; short sales are not supported"
            ) from error

        for allocation in allocations:
            connection.execute(
                """
                INSERT INTO lot_allocation (
                  lot_id, closing_event_id, quantity, allocated_cost
                )
                VALUES (%s, %s, %s, %s)
                """,
                (
                    allocation.lot_id,
                    event_id,
                    allocation.quantity,
                    allocation.allocated_cost,
                ),
            )
            connection.execute(
                """
                UPDATE lot
                SET remaining_quantity = remaining_quantity - %s
                WHERE id = %s
                """,
                (allocation.quantity, allocation.lot_id),
            )

    def store_secret(
        self,
        *,
        account_id: UUID | None,
        secret_type: str,
        ciphertext: bytes,
        nonce: bytes,
        auth_tag: bytes,
        aad_hash: bytes,
        key_version: int,
    ) -> UUID:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE encrypted_secret
                SET superseded_at = now()
                WHERE account_id IS NOT DISTINCT FROM %s
                  AND secret_type = %s
                  AND superseded_at IS NULL
                """,
                (account_id, secret_type),
            )
            row = connection.execute(
                """
                INSERT INTO encrypted_secret (
                  account_id, secret_type, ciphertext, nonce,
                  auth_tag, aad_hash, key_version
                )
                VALUES (%s, %s, %s, %s, %s, %s, %s)
                RETURNING id
                """,
                (
                    account_id,
                    secret_type,
                    ciphertext,
                    nonce,
                    auth_tag,
                    aad_hash,
                    key_version,
                ),
            ).fetchone()
            if row is None:
                raise RepositoryError("failed to store encrypted secret")
            connection.execute(
                """
                INSERT INTO secret_access_audit (
                  encrypted_secret_id, action, outcome
                )
                VALUES (%s, 'CREATE', 'SUCCESS')
                """,
                (row[0],),
            )
            return row[0]

    def start_job(self, job_type: str, idempotency_key: str) -> tuple[UUID, bool]:
        with self.connection() as connection:
            locked = connection.execute(
                "SELECT pg_try_advisory_xact_lock(hashtext(%s))",
                (job_type,),
            ).fetchone()
            if not locked or not locked[0]:
                raise RepositoryError("job lock is already held")
            row = connection.execute(
                """
                INSERT INTO job_run (
                  job_type, idempotency_key, status, attempt, started_at
                )
                VALUES (%s, %s, 'RUNNING', 1, now())
                ON CONFLICT (idempotency_key) DO NOTHING
                RETURNING id
                """,
                (job_type, idempotency_key),
            ).fetchone()
            if row is not None:
                return row[0], True
            existing = connection.execute(
                "SELECT id FROM job_run WHERE idempotency_key = %s",
                (idempotency_key,),
            ).fetchone()
            if existing is None:
                raise RepositoryError("job could not be loaded")
            return existing[0], False

    def checkpoint_job(
        self,
        job_id: UUID,
        checkpoint: dict[str, Any],
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE job_run
                SET checkpoint = %s
                WHERE id = %s AND status = 'RUNNING'
                """,
                (Jsonb(checkpoint), job_id),
            )

    def finish_job(
        self,
        job_id: UUID,
        *,
        status: str,
        checkpoint: dict[str, Any],
        error_code: str | None = None,
    ) -> None:
        if status not in {"SUCCEEDED", "FAILED", "PARTIAL"}:
            raise ValueError("invalid terminal job status")
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE job_run
                SET status = %s,
                    checkpoint = %s,
                    last_error_code = %s,
                    finished_at = now()
                WHERE id = %s AND status = 'RUNNING'
                """,
                (status, Jsonb(checkpoint), error_code, job_id),
            )

    def update_connector_state(
        self,
        connector: str,
        *,
        success: bool,
        received_at: datetime | None = None,
        imported: int = 0,
        duplicates: int = 0,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE connector_state
                SET last_checked_at = now(),
                    last_received_at = coalesce(%s, last_received_at),
                    last_success_at = CASE WHEN %s THEN now() ELSE last_success_at END,
                    imported_count = imported_count + %s,
                    duplicate_count = duplicate_count + %s,
                    error_count = error_count + CASE WHEN %s THEN 0 ELSE 1 END
                WHERE connector = %s
                """,
                (
                    received_at,
                    success,
                    imported,
                    duplicates,
                    success,
                    connector,
                ),
            )

    def upsert_fx_quotes(self, quotes: tuple[Any, ...]) -> int:
        count = 0
        with self.connection() as connection:
            for quote in quotes:
                connection.execute(
                    """
                    INSERT INTO fx_rate (
                      rate_date, base_currency, quote_currency, rate,
                      provider, quality, retrieved_at, convention
                    )
                    VALUES (%s, %s, %s, %s, %s, 'VERIFIED', now(), %s)
                    ON CONFLICT (rate_date, base_currency, quote_currency, provider)
                    DO UPDATE SET
                      rate = EXCLUDED.rate,
                      quality = EXCLUDED.quality,
                      retrieved_at = EXCLUDED.retrieved_at,
                      convention = EXCLUDED.convention
                    """,
                    (
                        quote.rate_date,
                        quote.base_currency,
                        quote.quote_currency,
                        quote.rate,
                        quote.provider,
                        quote.convention,
                    ),
                )
                count += 1
        return count

    def rebuild_position_snapshots(
        self,
        snapshot_date: date,
        reporting_currency: str,
    ) -> int:
        with self.connection() as connection:
            result = connection.execute(
                """
                WITH positions AS (
                  SELECT
                    le.account_id,
                    le.instrument_id,
                    sum(coalesce(le.quantity_delta, 0)) AS quantity
                  FROM ledger_event le
                  WHERE le.instrument_id IS NOT NULL
                    AND le.occurred_at::date <= %s
                  GROUP BY le.account_id, le.instrument_id
                  HAVING sum(coalesce(le.quantity_delta, 0)) <> 0
                ),
                valued AS (
                  SELECT
                    p.account_id,
                    p.instrument_id,
                    p.quantity,
                    selected_price.id AS price_id,
                    selected_fx.id AS fx_rate_id,
                    CASE
                      WHEN selected_price.id IS NULL THEN NULL
                      WHEN selected_price.currency = %s THEN
                        p.quantity * selected_price.close
                      WHEN selected_fx.id IS NULL THEN NULL
                      ELSE p.quantity * selected_price.close * selected_fx.factor
                    END AS market_value,
                    CASE
                      WHEN selected_price.id IS NULL THEN 'MISSING'::data_quality
                      WHEN selected_price.currency <> %s AND selected_fx.id IS NULL
                        THEN 'MISSING'::data_quality
                      WHEN %s - selected_price.price_date > 5
                        THEN 'STALE'::data_quality
                      ELSE selected_price.quality
                    END AS quality
                  FROM positions p
                  LEFT JOIN LATERAL (
                    SELECT pr.id, pr.close, pr.currency, pr.price_date, pr.quality
                    FROM price pr
                    WHERE pr.instrument_id = p.instrument_id
                      AND pr.price_date <= %s
                    ORDER BY
                      pr.price_date DESC,
                      CASE pr.quality
                        WHEN 'VERIFIED' THEN 0
                        WHEN 'ESTIMATED' THEN 1
                        ELSE 2
                      END,
                      pr.retrieved_at DESC
                    LIMIT 1
                  ) selected_price ON true
                  LEFT JOIN LATERAL (
                    SELECT
                      fx.id,
                      CASE
                        WHEN fx.base_currency = selected_price.currency
                          THEN fx.rate
                        ELSE 1 / fx.rate
                      END AS factor
                    FROM fx_rate fx
                    WHERE fx.rate_date <= %s
                      AND (
                        (
                          fx.base_currency = selected_price.currency
                          AND fx.quote_currency = %s
                        )
                        OR (
                          fx.quote_currency = selected_price.currency
                          AND fx.base_currency = %s
                        )
                      )
                    ORDER BY
                      fx.rate_date DESC,
                      CASE fx.quality WHEN 'VERIFIED' THEN 0 ELSE 1 END,
                      fx.retrieved_at DESC
                    LIMIT 1
                  ) selected_fx ON selected_price.currency <> %s
                )
                INSERT INTO position_snapshot (
                  snapshot_date, account_id, instrument_id, quantity,
                  price_id, fx_rate_id, market_value, reporting_currency,
                  quality
                )
                SELECT %s, account_id, instrument_id, quantity,
                       price_id, fx_rate_id, market_value, %s, quality
                FROM valued
                ON CONFLICT (
                  snapshot_date, account_id, instrument_id, reporting_currency
                )
                DO UPDATE SET
                  quantity = EXCLUDED.quantity,
                  price_id = EXCLUDED.price_id,
                  fx_rate_id = EXCLUDED.fx_rate_id,
                  market_value = EXCLUDED.market_value,
                  quality = EXCLUDED.quality
                """,
                (
                    snapshot_date,
                    reporting_currency,
                    reporting_currency,
                    snapshot_date,
                    snapshot_date,
                    snapshot_date,
                    reporting_currency,
                    reporting_currency,
                    reporting_currency,
                    snapshot_date,
                    reporting_currency,
                ),
            )
            self._update_position_cost_basis(
                connection,
                snapshot_date=snapshot_date,
                reporting_currency=reporting_currency,
            )
            self._rebuild_portfolio_snapshots(
                connection,
                snapshot_date=snapshot_date,
                reporting_currency=reporting_currency,
            )
            return result.rowcount

    def _update_position_cost_basis(
        self,
        connection: Connection[Any],
        *,
        snapshot_date: date,
        reporting_currency: str,
    ) -> None:
        connection.execute(
            """
            WITH bases AS (
              SELECT
                l.account_id,
                l.instrument_id,
                sum(
                  l.acquisition_cost
                  * l.remaining_quantity
                  / l.original_quantity
                  * portfolio_fx_factor(l.cost_currency, %s, %s)
                ) AS cost_basis,
                bool_or(
                  portfolio_fx_factor(l.cost_currency, %s, %s) IS NULL
                ) AS missing_fx
              FROM lot l
              WHERE l.remaining_quantity > 0
              GROUP BY l.account_id, l.instrument_id
            )
            UPDATE position_snapshot ps
            SET cost_basis = bases.cost_basis,
                unrealized_result = CASE
                  WHEN ps.market_value IS NULL
                    OR bases.cost_basis IS NULL
                    OR bases.missing_fx
                    THEN NULL
                  ELSE ps.market_value - bases.cost_basis
                END,
                quality = CASE
                  WHEN bases.missing_fx THEN 'MISSING'::data_quality
                  ELSE ps.quality
                END
            FROM bases
            WHERE ps.snapshot_date = %s
              AND ps.reporting_currency = %s
              AND ps.account_id = bases.account_id
              AND ps.instrument_id = bases.instrument_id
            """,
            (
                reporting_currency,
                snapshot_date,
                reporting_currency,
                snapshot_date,
                snapshot_date,
                reporting_currency,
            ),
        )
        connection.execute(
            """
            UPDATE position_snapshot ps
            SET cost_basis = NULL,
                unrealized_result = NULL,
                quality = CASE
                  WHEN ps.quality = 'VERIFIED' THEN 'PARTIAL'::data_quality
                  ELSE ps.quality
                END
            WHERE ps.snapshot_date = %s
              AND ps.reporting_currency = %s
              AND ps.quantity > 0
              AND NOT EXISTS (
                SELECT 1
                FROM lot l
                WHERE l.account_id = ps.account_id
                  AND l.instrument_id = ps.instrument_id
                  AND l.remaining_quantity > 0
              )
            """,
            (snapshot_date, reporting_currency),
        )

    def _rebuild_portfolio_snapshots(
        self,
        connection: Connection[Any],
        *,
        snapshot_date: date,
        reporting_currency: str,
    ) -> None:
        connection.execute(
            """
            WITH aggregates AS (
              SELECT
                a.id AS account_id,
                a.tax_wrapper,
                coalesce(sum(ps.market_value), 0) AS market_value,
                coalesce(bool_or(ps.quality = 'MISSING'), false) AS has_missing,
                coalesce(
                  bool_or(ps.quality IN ('STALE', 'PARTIAL')),
                  false
                ) AS has_partial,
                max(coalesce(pr.retrieved_at, ps.created_at)) AS price_as_of,
                max(coalesce(fx.retrieved_at, pr.retrieved_at, ps.created_at))
                  AS fx_as_of
              FROM account a
              LEFT JOIN position_snapshot ps
                ON ps.account_id = a.id
               AND ps.snapshot_date = %s
               AND ps.reporting_currency = %s
              LEFT JOIN price pr ON pr.id = ps.price_id
              LEFT JOIN fx_rate fx ON fx.id = ps.fx_rate_id
              WHERE (a.active_from IS NULL OR a.active_from <= %s)
                AND (a.active_to IS NULL OR a.active_to >= %s)
              GROUP BY a.id, a.tax_wrapper
            ),
            scopes AS (
              SELECT
                account_id,
                tax_wrapper,
                market_value,
                has_missing,
                has_partial,
                price_as_of,
                fx_as_of
              FROM aggregates
              UNION ALL
              SELECT
                NULL::uuid,
                tax_wrapper,
                sum(market_value),
                bool_or(has_missing),
                bool_or(has_partial),
                max(price_as_of),
                max(fx_as_of)
              FROM aggregates
              GROUP BY tax_wrapper
              UNION ALL
              SELECT
                NULL::uuid,
                NULL::tax_wrapper,
                sum(market_value),
                bool_or(has_missing),
                bool_or(has_partial),
                max(price_as_of),
                max(fx_as_of)
              FROM aggregates
            )
            INSERT INTO portfolio_snapshot (
              snapshot_date, reporting_currency, account_id, tax_wrapper,
              market_value, net_external_flow, daily_twr, cumulative_twr,
              price_set_as_of, fx_set_as_of, quality
            )
            SELECT
              %s,
              %s,
              account_id,
              tax_wrapper,
              coalesce(market_value, 0),
              0,
              NULL,
              NULL,
              coalesce(price_as_of, now()),
              coalesce(fx_as_of, price_as_of, now()),
              CASE
                WHEN has_missing THEN 'MISSING'::data_quality
                WHEN has_partial THEN 'PARTIAL'::data_quality
                ELSE 'VERIFIED'::data_quality
              END
            FROM scopes
            ON CONFLICT (
              snapshot_date, reporting_currency, account_id, tax_wrapper
            )
            DO UPDATE SET
              market_value = EXCLUDED.market_value,
              price_set_as_of = EXCLUDED.price_set_as_of,
              fx_set_as_of = EXCLUDED.fx_set_as_of,
              quality = EXCLUDED.quality
            """,
            (
                snapshot_date,
                reporting_currency,
                snapshot_date,
                snapshot_date,
                snapshot_date,
                reporting_currency,
            ),
        )
        self._update_portfolio_cash_and_metrics(
            connection,
            snapshot_date=snapshot_date,
            reporting_currency=reporting_currency,
        )
        connection.execute(
            """
            WITH previous AS (
              SELECT DISTINCT ON (
                current.id
              )
                current.id,
                prior.market_value AS prior_value,
                prior.cumulative_twr AS prior_twr
              FROM portfolio_snapshot current
              LEFT JOIN portfolio_snapshot prior
                ON prior.reporting_currency = current.reporting_currency
               AND prior.account_id IS NOT DISTINCT FROM current.account_id
               AND prior.tax_wrapper IS NOT DISTINCT FROM current.tax_wrapper
               AND prior.snapshot_date < current.snapshot_date
              WHERE current.snapshot_date = %s
                AND current.reporting_currency = %s
              ORDER BY current.id, prior.snapshot_date DESC
            )
            UPDATE portfolio_snapshot current
            SET daily_twr = CASE
                  WHEN previous.prior_value IS NULL
                    OR previous.prior_value = 0
                    OR current.quality = 'MISSING'
                    THEN NULL
                  ELSE (
                    current.market_value
                    - current.net_external_flow
                    - previous.prior_value
                  ) / previous.prior_value
                END,
                cumulative_twr = CASE
                  WHEN previous.prior_value IS NULL
                    OR previous.prior_value = 0
                    OR current.quality = 'MISSING'
                    THEN previous.prior_twr
                  ELSE
                    (1 + coalesce(previous.prior_twr, 0))
                    * (
                      1 + (
                        current.market_value
                        - current.net_external_flow
                        - previous.prior_value
                      ) / previous.prior_value
                    ) - 1
                END
            FROM previous
            WHERE current.id = previous.id
            """,
            (snapshot_date, reporting_currency),
        )

    def _update_portfolio_cash_and_metrics(
        self,
        connection: Connection[Any],
        *,
        snapshot_date: date,
        reporting_currency: str,
    ) -> None:
        connection.execute(
            """
            UPDATE portfolio_snapshot current
            SET market_value = current.market_value + coalesce(
                  (
                    SELECT sum(
                      cl.amount * portfolio_fx_factor(
                        cl.currency,
                        current.reporting_currency,
                        current.snapshot_date
                      )
                    )
                    FROM cash_leg cl
                    JOIN ledger_event le ON le.id = cl.ledger_event_id
                    JOIN account a ON a.id = le.account_id
                    WHERE le.occurred_at::date <= current.snapshot_date
                      AND (
                        current.account_id IS NULL
                        OR le.account_id = current.account_id
                      )
                      AND (
                        current.tax_wrapper IS NULL
                        OR a.tax_wrapper = current.tax_wrapper
                      )
                  ),
                  0
                ),
                net_external_flow = coalesce(
                  (
                    SELECT sum(
                      CASE
                        WHEN le.event_type IN ('DEPOSIT', 'TRANSFER_IN')
                          THEN abs(cl.amount)
                        WHEN le.event_type IN ('WITHDRAWAL', 'TRANSFER_OUT')
                          THEN -abs(cl.amount)
                        ELSE cl.amount
                      END
                      * portfolio_fx_factor(
                          cl.currency,
                          current.reporting_currency,
                          current.snapshot_date
                        )
                    )
                    FROM cash_leg cl
                    JOIN ledger_event le ON le.id = cl.ledger_event_id
                    JOIN account a ON a.id = le.account_id
                    WHERE le.external_cash_flow
                      AND cl.leg_type IN ('PRINCIPAL', 'OTHER')
                      AND le.occurred_at::date = current.snapshot_date
                      AND (
                        current.account_id IS NULL
                        OR le.account_id = current.account_id
                      )
                      AND (
                        current.tax_wrapper IS NULL
                        OR a.tax_wrapper = current.tax_wrapper
                      )
                  ),
                  0
                ),
                unrealized_result = (
                  SELECT sum(ps.unrealized_result)
                  FROM position_snapshot ps
                  JOIN account a ON a.id = ps.account_id
                  WHERE ps.snapshot_date = current.snapshot_date
                    AND ps.reporting_currency = current.reporting_currency
                    AND (
                      current.account_id IS NULL
                      OR ps.account_id = current.account_id
                    )
                    AND (
                      current.tax_wrapper IS NULL
                      OR a.tax_wrapper = current.tax_wrapper
                    )
                ),
                income = coalesce(
                  (
                    SELECT sum(
                      cl.amount * portfolio_fx_factor(
                        cl.currency,
                        current.reporting_currency,
                        le.occurred_at::date
                      )
                    )
                    FROM cash_leg cl
                    JOIN ledger_event le ON le.id = cl.ledger_event_id
                    JOIN account a ON a.id = le.account_id
                    WHERE cl.leg_type IN ('INCOME_GROSS', 'INCOME_NET')
                      AND le.occurred_at::date <= current.snapshot_date
                      AND (
                        current.account_id IS NULL
                        OR le.account_id = current.account_id
                      )
                      AND (
                        current.tax_wrapper IS NULL
                        OR a.tax_wrapper = current.tax_wrapper
                      )
                  ),
                  0
                ),
                fees = coalesce(
                  (
                    SELECT sum(
                      abs(cl.amount) * portfolio_fx_factor(
                        cl.currency,
                        current.reporting_currency,
                        le.occurred_at::date
                      )
                    )
                    FROM cash_leg cl
                    JOIN ledger_event le ON le.id = cl.ledger_event_id
                    JOIN account a ON a.id = le.account_id
                    WHERE cl.leg_type = 'FEE'
                      AND le.occurred_at::date <= current.snapshot_date
                      AND (
                        current.account_id IS NULL
                        OR le.account_id = current.account_id
                      )
                      AND (
                        current.tax_wrapper IS NULL
                        OR a.tax_wrapper = current.tax_wrapper
                      )
                  ),
                  0
                ),
                taxes = coalesce(
                  (
                    SELECT sum(
                      abs(cl.amount) * portfolio_fx_factor(
                        cl.currency,
                        current.reporting_currency,
                        le.occurred_at::date
                      )
                    )
                    FROM cash_leg cl
                    JOIN ledger_event le ON le.id = cl.ledger_event_id
                    JOIN account a ON a.id = le.account_id
                    WHERE cl.leg_type = 'TAX'
                      AND le.occurred_at::date <= current.snapshot_date
                      AND (
                        current.account_id IS NULL
                        OR le.account_id = current.account_id
                      )
                      AND (
                        current.tax_wrapper IS NULL
                        OR a.tax_wrapper = current.tax_wrapper
                      )
                  ),
                  0
                ),
                realized_result = coalesce(
                  (
                    SELECT sum(
                      event_cash.cash_result
                      - coalesce(event_cost.allocated_cost, 0)
                    )
                    FROM ledger_event le
                    JOIN account a ON a.id = le.account_id
                    JOIN LATERAL (
                      SELECT sum(
                        cl.amount * portfolio_fx_factor(
                          cl.currency,
                          current.reporting_currency,
                          le.occurred_at::date
                        )
                      ) AS cash_result
                      FROM cash_leg cl
                      WHERE cl.ledger_event_id = le.id
                        AND cl.leg_type IN ('PRINCIPAL', 'FEE', 'TAX')
                    ) event_cash ON true
                    LEFT JOIN LATERAL (
                      SELECT sum(
                        la.allocated_cost * portfolio_fx_factor(
                          l.cost_currency,
                          current.reporting_currency,
                          le.occurred_at::date
                        )
                      ) AS allocated_cost
                      FROM lot_allocation la
                      JOIN lot l ON l.id = la.lot_id
                      WHERE la.closing_event_id = le.id
                    ) event_cost ON true
                    WHERE le.event_type = 'SELL'
                      AND le.occurred_at::date <= current.snapshot_date
                      AND (
                        current.account_id IS NULL
                        OR le.account_id = current.account_id
                      )
                      AND (
                        current.tax_wrapper IS NULL
                        OR a.tax_wrapper = current.tax_wrapper
                      )
                  ),
                  0
                )
            WHERE current.snapshot_date = %s
              AND current.reporting_currency = %s
            """,
            (snapshot_date, reporting_currency),
        )
        rows = connection.execute(
            """
            SELECT id, account_id, tax_wrapper, market_value
            FROM portfolio_snapshot
            WHERE snapshot_date = %s
              AND reporting_currency = %s
            """,
            (snapshot_date, reporting_currency),
        ).fetchall()
        for snapshot_id, account_id, tax_wrapper, market_value in rows:
            flows = connection.execute(
                """
                SELECT
                  le.occurred_at::date,
                  sum(
                    CASE
                      WHEN le.event_type IN ('DEPOSIT', 'TRANSFER_IN')
                        THEN -abs(cl.amount)
                      WHEN le.event_type IN ('WITHDRAWAL', 'TRANSFER_OUT')
                        THEN abs(cl.amount)
                      ELSE -cl.amount
                    END
                    * portfolio_fx_factor(cl.currency, %s, le.occurred_at::date)
                  )
                FROM ledger_event le
                JOIN cash_leg cl ON cl.ledger_event_id = le.id
                JOIN account a ON a.id = le.account_id
                WHERE le.external_cash_flow
                  AND cl.leg_type IN ('PRINCIPAL', 'OTHER')
                  AND le.occurred_at::date <= %s
                  AND (%s::uuid IS NULL OR le.account_id = %s::uuid)
                  AND (%s::tax_wrapper IS NULL OR a.tax_wrapper = %s::tax_wrapper)
                GROUP BY le.occurred_at::date
                ORDER BY le.occurred_at::date
                """,
                (
                    reporting_currency,
                    snapshot_date,
                    account_id,
                    account_id,
                    tax_wrapper,
                    tax_wrapper,
                ),
            ).fetchall()
            cash_flows = [
                (flow_date, Decimal(flow_amount))
                for flow_date, flow_amount in flows
                if flow_amount is not None and flow_amount != 0
            ]
            if market_value != 0:
                cash_flows.append((snapshot_date, Decimal(market_value)))
            connection.execute(
                "UPDATE portfolio_snapshot SET xirr = %s WHERE id = %s",
                (xirr(cash_flows), snapshot_id),
            )

    def rebuild_exposure_snapshots(
        self,
        snapshot_date: date,
        reporting_currency: str,
    ) -> int:
        with self.connection() as connection:
            connection.execute(
                """
                DELETE FROM exposure_snapshot
                WHERE snapshot_date = %s
                  AND reporting_currency = %s
                """,
                (snapshot_date, reporting_currency),
            )
            result = connection.execute(
                """
                WITH positions AS (
                  SELECT
                    ps.account_id,
                    a.tax_wrapper,
                    ps.instrument_id,
                    ps.market_value,
                    i.name,
                    i.asset_class,
                    i.domicile_country,
                    i.metadata,
                    pr.currency AS listing_currency
                  FROM position_snapshot ps
                  JOIN account a ON a.id = ps.account_id
                  JOIN instrument i ON i.id = ps.instrument_id
                  LEFT JOIN price pr ON pr.id = ps.price_id
                  WHERE ps.snapshot_date = %s
                    AND ps.reporting_currency = %s
                    AND ps.market_value IS NOT NULL
                    AND ps.market_value > 0
                ),
                latest_holding_dates AS (
                  SELECT
                    fund_instrument_id,
                    max(holding_date) AS holding_date
                  FROM fund_holding_snapshot
                  WHERE holding_date <= %s
                  GROUP BY fund_instrument_id
                ),
                holdings AS (
                  SELECT fhs.*
                  FROM fund_holding_snapshot fhs
                  JOIN latest_holding_dates latest
                    ON latest.fund_instrument_id = fhs.fund_instrument_id
                   AND latest.holding_date = fhs.holding_date
                ),
                coverage AS (
                  SELECT
                    p.account_id,
                    p.instrument_id,
                    coalesce(sum(h.weight), 0) AS covered_weight
                  FROM positions p
                  LEFT JOIN holdings h
                    ON h.fund_instrument_id = p.instrument_id
                  GROUP BY p.account_id, p.instrument_id
                ),
                direct_rows AS (
                  SELECT
                    p.account_id,
                    p.tax_wrapper,
                    'ASSET_CLASS'::exposure_dimension AS dimension,
                    p.asset_class::text AS exposure_key,
                    initcap(replace(p.asset_class::text, '_', ' ')) AS label,
                    'DIRECT'::exposure_source AS source,
                    p.market_value AS value
                  FROM positions p
                  UNION ALL
                  SELECT
                    p.account_id,
                    p.tax_wrapper,
                    'UNDERLYING'::exposure_dimension,
                    p.instrument_id::text,
                    p.name,
                    'DIRECT'::exposure_source,
                    p.market_value
                  FROM positions p
                  WHERE NOT EXISTS (
                    SELECT 1
                    FROM holdings h
                    WHERE h.fund_instrument_id = p.instrument_id
                  )
                  UNION ALL
                  SELECT
                    p.account_id,
                    p.tax_wrapper,
                    dimension,
                    coalesce(exposure_key, 'Unknown'),
                    coalesce(label, 'Unknown'),
                    CASE
                      WHEN exposure_key IS NULL
                        THEN 'UNKNOWN'::exposure_source
                      ELSE 'DIRECT'::exposure_source
                    END,
                    p.market_value
                  FROM positions p
                  CROSS JOIN LATERAL (
                    VALUES
                      (
                        'GEOGRAPHY'::exposure_dimension,
                        p.domicile_country::text,
                        p.domicile_country::text
                      ),
                      (
                        'SECTOR'::exposure_dimension,
                        p.metadata ->> 'sector',
                        p.metadata ->> 'sector'
                      ),
                      (
                        'CURRENCY'::exposure_dimension,
                        p.listing_currency::text,
                        p.listing_currency::text
                      )
                  ) descriptors(dimension, exposure_key, label)
                  WHERE NOT EXISTS (
                    SELECT 1
                    FROM holdings h
                    WHERE h.fund_instrument_id = p.instrument_id
                  )
                ),
                look_through_rows AS (
                  SELECT
                    p.account_id,
                    p.tax_wrapper,
                    descriptors.dimension,
                    coalesce(descriptors.exposure_key, 'Unknown'),
                    coalesce(descriptors.label, 'Unknown'),
                    CASE
                      WHEN descriptors.exposure_key IS NULL
                        THEN 'UNKNOWN'::exposure_source
                      ELSE 'LOOK_THROUGH'::exposure_source
                    END,
                    p.market_value * h.weight
                  FROM positions p
                  JOIN holdings h
                    ON h.fund_instrument_id = p.instrument_id
                  CROSS JOIN LATERAL (
                    VALUES
                      (
                        'GEOGRAPHY'::exposure_dimension,
                        h.country_code::text,
                        h.country_code::text
                      ),
                      (
                        'SECTOR'::exposure_dimension,
                        h.sector,
                        h.sector
                      ),
                      (
                        'CURRENCY'::exposure_dimension,
                        h.economic_currency::text,
                        h.economic_currency::text
                      ),
                      (
                        'UNDERLYING'::exposure_dimension,
                        coalesce(
                          h.underlying_isin::text,
                          h.underlying_name
                        ),
                        h.underlying_name
                      )
                  ) descriptors(dimension, exposure_key, label)
                  UNION ALL
                  SELECT
                    p.account_id,
                    p.tax_wrapper,
                    dimension,
                    'Unknown',
                    'Unknown',
                    'UNKNOWN'::exposure_source,
                    p.market_value * greatest(0, 1 - c.covered_weight)
                  FROM positions p
                  JOIN coverage c
                    ON c.account_id = p.account_id
                   AND c.instrument_id = p.instrument_id
                  CROSS JOIN (
                    VALUES
                      ('GEOGRAPHY'::exposure_dimension),
                      ('SECTOR'::exposure_dimension),
                      ('CURRENCY'::exposure_dimension),
                      ('UNDERLYING'::exposure_dimension)
                  ) dimensions(dimension)
                  WHERE c.covered_weight < 1
                    AND EXISTS (
                      SELECT 1
                      FROM holdings h
                      WHERE h.fund_instrument_id = p.instrument_id
                    )
                ),
                account_rows AS (
                  SELECT * FROM direct_rows
                  UNION ALL
                  SELECT * FROM look_through_rows
                ),
                scoped_rows AS (
                  SELECT
                    account_id,
                    tax_wrapper,
                    dimension,
                    exposure_key,
                    label,
                    source,
                    value
                  FROM account_rows
                  UNION ALL
                  SELECT
                    NULL::uuid,
                    tax_wrapper,
                    dimension,
                    exposure_key,
                    label,
                    source,
                    value
                  FROM account_rows
                  UNION ALL
                  SELECT
                    NULL::uuid,
                    NULL::tax_wrapper,
                    dimension,
                    exposure_key,
                    label,
                    source,
                    value
                  FROM account_rows
                ),
                grouped AS (
                  SELECT
                    account_id,
                    tax_wrapper,
                    dimension,
                    exposure_key,
                    label,
                    source,
                    sum(value) AS value
                  FROM scoped_rows
                  WHERE value > 0
                  GROUP BY
                    account_id,
                    tax_wrapper,
                    dimension,
                    exposure_key,
                    label,
                    source
                ),
                denominators AS (
                  SELECT
                    account_id,
                    tax_wrapper,
                    dimension,
                    sum(value) AS total_value,
                    sum(value) FILTER (
                      WHERE source <> 'UNKNOWN'
                    ) AS known_value
                  FROM grouped
                  GROUP BY account_id, tax_wrapper, dimension
                )
                INSERT INTO exposure_snapshot (
                  snapshot_date,
                  reporting_currency,
                  account_id,
                  tax_wrapper,
                  dimension,
                  exposure_key,
                  label,
                  source,
                  value,
                  weight,
                  coverage
                )
                SELECT
                  %s,
                  %s,
                  grouped.account_id,
                  grouped.tax_wrapper,
                  grouped.dimension,
                  grouped.exposure_key,
                  grouped.label,
                  grouped.source,
                  grouped.value,
                  grouped.value / denominators.total_value,
                  coalesce(
                    denominators.known_value / denominators.total_value,
                    0
                  )
                FROM grouped
                JOIN denominators
                  ON denominators.account_id
                       IS NOT DISTINCT FROM grouped.account_id
                 AND denominators.tax_wrapper
                       IS NOT DISTINCT FROM grouped.tax_wrapper
                 AND denominators.dimension = grouped.dimension
                """,
                (
                    snapshot_date,
                    reporting_currency,
                    snapshot_date,
                    snapshot_date,
                    reporting_currency,
                ),
            )
            return result.rowcount

    def rebuild_benchmark_series(
        self,
        series_date: date,
        reporting_currency: str,
    ) -> int:
        with self.connection() as connection:
            result = connection.execute(
                """
                WITH quotes AS (
                  SELECT
                    b.id AS benchmark_id,
                    current_price.id AS price_id,
                    current_price.price_date,
                    current_price.close
                      * portfolio_fx_factor(
                          current_price.currency,
                          %s,
                          current_price.price_date
                        ) AS current_value,
                    base_price.close
                      * portfolio_fx_factor(
                          base_price.currency,
                          %s,
                          base_price.price_date
                        ) AS base_value,
                    current_price.quality,
                    current_price.retrieved_at
                  FROM benchmark b
                  JOIN LATERAL (
                    SELECT p.*
                    FROM price p
                    WHERE p.instrument_id = b.proxy_instrument_id
                      AND (
                        b.proxy_listing_id IS NULL
                        OR p.listing_id = b.proxy_listing_id
                      )
                      AND p.price_date <= %s
                    ORDER BY p.price_date DESC, p.retrieved_at DESC
                    LIMIT 1
                  ) current_price ON true
                  JOIN LATERAL (
                    SELECT p.*
                    FROM price p
                    WHERE p.instrument_id = b.proxy_instrument_id
                      AND (
                        b.proxy_listing_id IS NULL
                        OR p.listing_id = b.proxy_listing_id
                      )
                      AND p.price_date >= b.valid_from
                      AND p.price_date <= %s
                    ORDER BY p.price_date, p.retrieved_at
                    LIMIT 1
                  ) base_price ON true
                  WHERE b.valid_from <= %s
                    AND (b.valid_to IS NULL OR b.valid_to >= %s)
                )
                INSERT INTO benchmark_series (
                  benchmark_id, series_date, reporting_currency,
                  normalized_value, price_id, fx_rate_id, quality
                )
                SELECT
                  benchmark_id,
                  %s,
                  %s,
                  current_value / base_value,
                  price_id,
                  NULL,
                  CASE
                    WHEN current_value IS NULL OR base_value IS NULL
                      THEN 'MISSING'::data_quality
                    WHEN %s - price_date > 5
                      THEN 'STALE'::data_quality
                    ELSE quality
                  END
                FROM quotes
                WHERE current_value IS NOT NULL
                  AND base_value IS NOT NULL
                  AND base_value <> 0
                ON CONFLICT (
                  benchmark_id, series_date, reporting_currency
                )
                DO UPDATE SET
                  normalized_value = EXCLUDED.normalized_value,
                  price_id = EXCLUDED.price_id,
                  fx_rate_id = EXCLUDED.fx_rate_id,
                  quality = EXCLUDED.quality
                """,
                (
                    reporting_currency,
                    reporting_currency,
                    series_date,
                    series_date,
                    series_date,
                    series_date,
                    series_date,
                    reporting_currency,
                    series_date,
                ),
            )
            return result.rowcount

    def refresh_data_quality_issues(self, snapshot_date: date) -> int:
        with self.connection() as connection:
            connection.execute(
                """
                UPDATE data_quality_issue issue
                SET status = 'RESOLVED',
                    resolved_at = now(),
                    resolution_note = 'Resolved by a later valuation snapshot'
                WHERE issue.code IN ('PRICE_OR_FX_MISSING', 'VALUATION_STALE')
                  AND issue.status <> 'RESOLVED'
                  AND NOT EXISTS (
                    SELECT 1
                    FROM position_snapshot ps
                    WHERE ps.account_id = issue.account_id
                      AND ps.instrument_id = issue.instrument_id
                      AND ps.snapshot_date = %s
                      AND (
                        (
                          issue.code = 'PRICE_OR_FX_MISSING'
                          AND ps.quality = 'MISSING'
                        )
                        OR (
                          issue.code = 'VALUATION_STALE'
                          AND ps.quality = 'STALE'
                        )
                      )
                  )
                """,
                (snapshot_date,),
            )
            result = connection.execute(
                """
                INSERT INTO data_quality_issue (
                  code, severity, account_id, instrument_id, summary
                )
                SELECT
                  CASE
                    WHEN ps.quality = 'MISSING' THEN 'PRICE_OR_FX_MISSING'
                    ELSE 'VALUATION_STALE'
                  END,
                  CASE
                    WHEN ps.quality = 'MISSING'
                      THEN 'ERROR'::issue_severity
                    ELSE 'WARNING'::issue_severity
                  END,
                  ps.account_id,
                  ps.instrument_id,
                  CASE
                    WHEN ps.quality = 'MISSING'
                      THEN 'Position is missing a usable price or FX rate.'
                    ELSE 'Position uses a stale valuation input.'
                  END
                FROM position_snapshot ps
                WHERE ps.snapshot_date = %s
                  AND ps.quality IN ('MISSING', 'STALE')
                  AND NOT EXISTS (
                    SELECT 1
                    FROM data_quality_issue existing
                    WHERE existing.account_id = ps.account_id
                      AND existing.instrument_id = ps.instrument_id
                      AND existing.status <> 'RESOLVED'
                      AND existing.code = CASE
                        WHEN ps.quality = 'MISSING'
                          THEN 'PRICE_OR_FX_MISSING'
                        ELSE 'VALUATION_STALE'
                      END
                  )
                """,
                (snapshot_date,),
            )
            return result.rowcount

    def export_backup_tables(self) -> dict[str, list[dict[str, Any]]]:
        table_names = (
            "broker",
            "account",
            "instrument",
            "listing",
            "raw_import",
            "broker_order",
            "execution_leg",
            "ledger_event",
            "cash_leg",
            "lot",
            "lot_allocation",
            "job_run",
            "encrypted_secret",
            "secret_access_audit",
            "price",
            "fx_rate",
            "position_snapshot",
            "portfolio_snapshot",
            "fund_holding_snapshot",
            "exposure_snapshot",
            "benchmark",
            "benchmark_series",
            "connector_state",
            "reconciliation_run",
            "reconciliation_item",
            "data_quality_issue",
        )
        exported: dict[str, list[dict[str, Any]]] = {}
        with self.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                for table_name in table_names:
                    cursor.execute(
                        sql.SQL("SELECT * FROM {}").format(
                            sql.Identifier(table_name)
                        )
                    )
                    exported[table_name] = [dict(row) for row in cursor.fetchall()]
        return exported

    def load_active_secret(
        self,
        *,
        account_id: UUID | None,
        secret_type: str,
    ) -> tuple[UUID, SecretEnvelope]:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT id, ciphertext, nonce, auth_tag, aad_hash, key_version
                FROM encrypted_secret
                WHERE account_id IS NOT DISTINCT FROM %s
                  AND secret_type = %s
                  AND superseded_at IS NULL
                """,
                (account_id, secret_type),
            ).fetchone()
        if row is None:
            raise RepositoryError("required encrypted secret is not configured")
        return (
            row[0],
            SecretEnvelope(
                ciphertext=row[1],
                nonce=row[2],
                auth_tag=row[3],
                aad_hash=row[4],
                key_version=row[5],
            ),
        )

    def audit_secret_access(
        self,
        secret_id: UUID,
        *,
        outcome: str,
    ) -> None:
        if outcome not in {"SUCCESS", "DENIED", "FAILED"}:
            raise ValueError("invalid secret audit outcome")
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO secret_access_audit (
                  encrypted_secret_id, action, outcome
                )
                VALUES (%s, 'DECRYPT', %s)
                """,
                (secret_id, outcome),
            )

    def connector_after_epoch(
        self,
        connector: str,
        *,
        overlap_seconds: int = 172800,
    ) -> int:
        with self.connection() as connection:
            row = connection.execute(
                """
                SELECT extract(
                  epoch FROM (
                    coalesce(last_success_at, now() - interval '30 days')
                    - make_interval(secs => %s)
                  )
                )::bigint
                FROM connector_state
                WHERE connector = %s
                """,
                (overlap_seconds, connector),
            ).fetchone()
        if row is None:
            raise RepositoryError("connector is not configured")
        return int(row[0])

    def list_price_targets(self) -> list[dict[str, Any]]:
        with self.connection() as connection:
            with connection.cursor(row_factory=dict_row) as cursor:
                cursor.execute(
                    """
                    SELECT
                      l.id AS listing_id,
                      l.instrument_id,
                      l.trading_currency AS currency,
                      l.provider_symbols
                    FROM listing l
                    JOIN instrument i ON i.id = l.instrument_id
                    WHERE l.is_primary
                       OR NOT EXISTS (
                         SELECT 1
                         FROM listing primary_listing
                         WHERE primary_listing.instrument_id = i.id
                           AND primary_listing.is_primary
                       )
                    ORDER BY l.instrument_id, l.is_primary DESC, l.created_at
                    """
                )
                rows = cursor.fetchall()
        seen: set[UUID] = set()
        targets: list[dict[str, Any]] = []
        for row in rows:
            instrument_id = row["instrument_id"]
            if instrument_id in seen:
                continue
            seen.add(instrument_id)
            targets.append(
                {
                    "listing_id": row["listing_id"],
                    "instrument_id": instrument_id,
                    "currency": str(row["currency"]).strip(),
                    "provider_symbols": dict(
                        row["provider_symbols"] or {}
                    ),
                }
            )
        return targets

    def upsert_price_quote(
        self,
        *,
        listing_id: UUID,
        instrument_id: UUID,
        quote: Any,
    ) -> None:
        with self.connection() as connection:
            connection.execute(
                """
                INSERT INTO price (
                  listing_id, instrument_id, price_date, close,
                  currency, provider, quality, retrieved_at
                )
                VALUES (%s, %s, %s, %s, %s, %s, 'VERIFIED', now())
                ON CONFLICT (
                  instrument_id, listing_id, price_date, provider
                )
                DO UPDATE SET
                  close = EXCLUDED.close,
                  currency = EXCLUDED.currency,
                  quality = EXCLUDED.quality,
                  retrieved_at = EXCLUDED.retrieved_at
                """,
                (
                    listing_id,
                    instrument_id,
                    quote.price_date,
                    quote.close,
                    quote.currency,
                    quote.provider,
                ),
            )
