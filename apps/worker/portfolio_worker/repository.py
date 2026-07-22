from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import datetime
from typing import Any
from uuid import UUID

import psycopg
from psycopg import Connection
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
