from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone

from .fingerprint import source_fingerprint
from .parsers import PatriaHtmlParser, XtbCsvParser
from .parsers.base import ParseError
from .repository import WorkerRepository


@dataclass(frozen=True, slots=True)
class ImportResult:
    raw_import_id: str
    accepted: int
    duplicates: int
    duplicate_document: bool


class ImportService:
    def __init__(self, repository: WorkerRepository) -> None:
        self._repository = repository

    def import_payload(
        self,
        *,
        broker_code: str,
        account_ref: str,
        payload: bytes,
        content_type: str,
        source_channel: str = "UPLOAD",
        received_at: datetime | None = None,
        gmail_message_id: str | None = None,
        mime_part_id: str | None = None,
    ) -> ImportResult:
        received = received_at or datetime.now(timezone.utc)
        broker = broker_code.upper()
        if broker == "PATRIA" and content_type.startswith("text/html"):
            parser = PatriaHtmlParser()
            events = parser.parse(payload.decode("utf-8"), account_ref=account_ref)
            document_type = "PATRIA_TRADE_HTML"
        elif broker == "XTB" and (
            content_type.startswith("text/csv") or content_type == "application/csv"
        ):
            parser = XtbCsvParser()
            events = parser.parse(payload.decode("utf-8-sig"), account_ref=account_ref)
            document_type = "XTB_HISTORY_CSV"
        else:
            raise ParseError("unsupported broker document type")

        account_id = self._repository.resolve_account(broker, account_ref)
        import_id, created = self._repository.register_import(
            broker_code=broker,
            account_id=account_id,
            source_channel=source_channel,
            document_type=document_type,
            source_fingerprint=source_fingerprint(payload),
            parser_version=parser.version,
            received_at=received,
            gmail_message_id=gmail_message_id,
            mime_part_id=mime_part_id,
        )
        if not created:
            return ImportResult(
                raw_import_id=str(import_id),
                accepted=0,
                duplicates=len(events),
                duplicate_document=True,
            )
        accepted, duplicates = self._repository.post_batch(
            raw_import_id=import_id,
            account_id=account_id,
            events=events,
        )
        return ImportResult(
            raw_import_id=str(import_id),
            accepted=accepted,
            duplicates=duplicates,
            duplicate_document=False,
        )
