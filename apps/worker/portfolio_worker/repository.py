from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date, datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection, sql
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from .fingerprint import economic_fingerprint, sha256_json
from .models import NormalizedEvent


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
    ) -> tuple[UUID, bool]:
        with self.connection() as connection:
            row = connection.execute(
                """
                INSERT INTO raw_import (
                  broker_id, account_id, source_channel, document_type,
                  gmail_message_id, mime_part_id, source_fingerprint,
                  parser_version, received_at
                )
                SELECT
                  b.id, %s, %s, %s, %s, %s, %s, %s, %s
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
            self._rebuild_portfolio_snapshots(
                connection,
                snapshot_date=snapshot_date,
                reporting_currency=reporting_currency,
            )
            return result.rowcount

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
                ps.account_id,
                a.tax_wrapper,
                sum(ps.market_value) AS market_value,
                bool_or(ps.quality = 'MISSING') AS has_missing,
                bool_or(ps.quality IN ('STALE', 'PARTIAL')) AS has_partial,
                max(coalesce(pr.retrieved_at, ps.created_at)) AS price_as_of,
                max(coalesce(fx.retrieved_at, pr.retrieved_at, ps.created_at))
                  AS fx_as_of
              FROM position_snapshot ps
              JOIN account a ON a.id = ps.account_id
              LEFT JOIN price pr ON pr.id = ps.price_id
              LEFT JOIN fx_rate fx ON fx.id = ps.fx_rate_id
              WHERE ps.snapshot_date = %s
                AND ps.reporting_currency = %s
              GROUP BY ps.account_id, a.tax_wrapper
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
                reporting_currency,
            ),
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
            "encrypted_secret",
            "price",
            "fx_rate",
            "position_snapshot",
            "portfolio_snapshot",
            "fund_holding_snapshot",
            "exposure_snapshot",
            "benchmark",
            "benchmark_series",
            "connector_state",
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
