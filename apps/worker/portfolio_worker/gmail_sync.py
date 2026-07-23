from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, TypeAdapter

from .archive import EncryptedArchive, VercelBlobWriter
from .config import Settings
from .crypto import InvalidSecret, SecretBox
from .gmail import GmailClient, GmailMessage, GmailPart
from .import_service import ImportService
from .models import SecretKind
from .repository import WorkerRepository


class GmailImportRule(BaseModel):
    connector: Literal["GMAIL_GEORGE", "GMAIL_XTB", "GMAIL_PATRIA"]
    query: str = Field(
        min_length=1,
        description="Gmail query containing both a label and allowed sender.",
    )
    broker_code: Literal["GEORGE", "XTB", "PATRIA"]
    account_ref: str = Field(min_length=1, max_length=120)


@dataclass(frozen=True, slots=True)
class GmailSyncResult:
    checked_messages: int
    imported_events: int
    duplicate_events: int
    errors: int


def parse_rules(payload: str) -> tuple[GmailImportRule, ...]:
    raw = json.loads(payload)
    rules = TypeAdapter(list[GmailImportRule]).validate_python(raw)
    if not rules:
        raise ValueError("at least one Gmail import rule is required")
    for rule in rules:
        normalized = rule.query.lower()
        if "label:" not in normalized or "from:" not in normalized:
            raise ValueError("every Gmail rule must restrict both label and sender")
    return tuple(rules)


class GmailSync:
    def __init__(
        self,
        repository: WorkerRepository,
        settings: Settings,
    ) -> None:
        self._repository = repository
        self._settings = settings
        self._box = SecretBox(settings.require("master_encryption_key"))
        self._archive = EncryptedArchive(
            box=self._box,
            writer=VercelBlobWriter(
                token=settings.require("blob_token"),
            ),
        )

    def run(self) -> GmailSyncResult:
        secret_id, envelope = self._repository.load_active_secret(
            account_id=None,
            secret_type=SecretKind.GMAIL_REFRESH.value,
        )
        try:
            refresh_token = self._box.decrypt_secret(
                envelope,
                account_id=None,
                secret_type=SecretKind.GMAIL_REFRESH.value,
            ).decode()
        except (InvalidSecret, UnicodeDecodeError):
            self._repository.audit_secret_access(
                secret_id,
                outcome="FAILED",
            )
            raise
        self._repository.audit_secret_access(
            secret_id,
            outcome="SUCCESS",
        )
        client = GmailClient(
            refresh_token=refresh_token,
            client_id=self._settings.require("gmail_client_id"),
            client_secret=self._settings.require("gmail_client_secret"),
        )

        checked = imported = duplicates = errors = 0
        rules = parse_rules(
            self._settings.require("gmail_import_rules_json")
        )
        for rule in rules:
            after_epoch = self._repository.connector_after_epoch(
                rule.connector
            )
            message_ids = client.list_message_ids(
                query=rule.query,
                after_epoch=after_epoch,
            )
            rule_imported = rule_duplicates = rule_errors = 0
            latest_received = None
            for message_id in message_ids:
                checked += 1
                try:
                    message = client.get_message(message_id)
                    accepted, duplicate_count = self._import_message(
                        message,
                        rule,
                    )
                except Exception:
                    errors += 1
                    rule_errors += 1
                    self._repository.update_connector_state(
                        rule.connector,
                        success=False,
                    )
                    continue
                latest_received = max(
                    latest_received or message.received_at,
                    message.received_at,
                )
                rule_imported += accepted
                rule_duplicates += duplicate_count
            imported += rule_imported
            duplicates += rule_duplicates
            self._repository.update_connector_state(
                rule.connector,
                success=rule_errors == 0,
                received_at=latest_received,
                imported=rule_imported,
                duplicates=rule_duplicates,
            )
        return GmailSyncResult(
            checked_messages=checked,
            imported_events=imported,
            duplicate_events=duplicates,
            errors=errors,
        )

    def _import_message(
        self,
        message: GmailMessage,
        rule: GmailImportRule,
    ) -> tuple[int, int]:
        parts = self._parts_for_rule(message, rule)
        accepted = duplicates = 0
        for part in parts:
            content_type = self._content_type(part)
            password = (
                self._pdf_password(rule.broker_code, rule.account_ref)
                if rule.broker_code in {"XTB", "GEORGE"}
                and content_type == "application/pdf"
                else None
            )
            result = ImportService(
                self._repository,
                archive=self._archive,
            ).import_payload(
                broker_code=rule.broker_code,
                account_ref=rule.account_ref,
                payload=part.data,
                content_type=content_type,
                source_channel="GMAIL",
                received_at=message.received_at,
                gmail_message_id=message.message_id,
                mime_part_id=part.part_id,
                pdf_password=password,
            )
            accepted += result.accepted
            duplicates += result.duplicates
            if result.duplicate_document:
                duplicates += 1
        return accepted, duplicates

    @staticmethod
    def _parts_for_rule(
        message: GmailMessage,
        rule: GmailImportRule,
    ) -> tuple[GmailPart, ...]:
        if rule.broker_code == "PATRIA":
            return message.html_bodies
        return message.attachments

    @staticmethod
    def _content_type(part: GmailPart) -> str:
        suffix = Path(part.filename).suffix.lower()
        if suffix == ".pdf":
            return "application/pdf"
        if suffix == ".csv":
            return "text/csv"
        if suffix in {".html", ".htm"}:
            return "text/html"
        return part.mime_type

    def _pdf_password(self, broker_code: str, account_ref: str) -> str:
        secret_kind = {
            "XTB": SecretKind.XTB_PDF,
            "GEORGE": SecretKind.GEORGE_PDF,
        }[broker_code]
        account_id = self._repository.resolve_account(
            broker_code,
            account_ref,
        )
        secret_id, envelope = self._repository.load_active_secret(
            account_id=account_id,
            secret_type=secret_kind.value,
        )
        try:
            password = self._box.decrypt_secret(
                envelope,
                account_id=account_id,
                secret_type=secret_kind.value,
            ).decode()
        except (InvalidSecret, UnicodeDecodeError):
            self._repository.audit_secret_access(
                secret_id,
                outcome="FAILED",
            )
            raise
        self._repository.audit_secret_access(
            secret_id,
            outcome="SUCCESS",
        )
        return password
