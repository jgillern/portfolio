from __future__ import annotations

import base64
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build

GOOGLE_TOKEN_URI = "https://oauth2.googleapis.com/token"


@dataclass(frozen=True, slots=True)
class GmailPart:
    part_id: str
    attachment_id: str | None
    mime_type: str
    filename: str
    data: bytes


@dataclass(frozen=True, slots=True)
class GmailMessage:
    message_id: str
    received_at: datetime
    html_bodies: tuple[GmailPart, ...]
    text_bodies: tuple[GmailPart, ...]
    attachments: tuple[GmailPart, ...]


def _decode(data: str | None) -> bytes:
    if not data:
        return b""
    padding = "=" * (-len(data) % 4)
    return base64.urlsafe_b64decode(data + padding)


def decode_message(message: dict[str, Any]) -> GmailMessage:
    html: list[GmailPart] = []
    text: list[GmailPart] = []
    attachments: list[GmailPart] = []

    def visit(part: dict[str, Any]) -> None:
        body = part.get("body") or {}
        item = GmailPart(
            part_id=part.get("partId") or "",
            attachment_id=body.get("attachmentId"),
            mime_type=part.get("mimeType") or "application/octet-stream",
            filename=part.get("filename") or "",
            data=_decode(body.get("data")),
        )
        if item.filename:
            attachments.append(item)
        elif item.mime_type == "text/html":
            html.append(item)
        elif item.mime_type == "text/plain":
            text.append(item)
        for child in part.get("parts") or []:
            visit(child)

    visit(message.get("payload") or {})
    received_at = datetime.fromtimestamp(
        int(message.get("internalDate") or "0") / 1000,
        tz=UTC,
    )
    return GmailMessage(
        message_id=message["id"],
        received_at=received_at,
        html_bodies=tuple(html),
        text_bodies=tuple(text),
        attachments=tuple(attachments),
    )


class GmailClient:
    def __init__(
        self,
        *,
        refresh_token: str,
        client_id: str,
        client_secret: str,
    ) -> None:
        credentials = Credentials(
            token=None,
            refresh_token=refresh_token,
            token_uri=GOOGLE_TOKEN_URI,
            client_id=client_id,
            client_secret=client_secret,
            scopes=["https://www.googleapis.com/auth/gmail.readonly"],
        )
        self._service = build("gmail", "v1", credentials=credentials, cache_discovery=False)

    def list_message_ids(self, *, label: str, after_epoch: int, limit: int = 100) -> list[str]:
        response = (
            self._service.users()
            .messages()
            .list(
                userId="me",
                q=f"label:{label} after:{after_epoch}",
                maxResults=min(limit, 500),
            )
            .execute()
        )
        return [item["id"] for item in response.get("messages", [])]

    def get_message(self, message_id: str) -> GmailMessage:
        raw = (
            self._service.users()
            .messages()
            .get(userId="me", id=message_id, format="full")
            .execute()
        )
        message = decode_message(raw)
        parts: list[GmailPart] = []
        for part in message.attachments:
            if part.data or not part.attachment_id:
                parts.append(part)
                continue
            attachment = (
                self._service.users()
                .messages()
                .attachments()
                .get(
                    userId="me",
                    messageId=message_id,
                    id=part.attachment_id,
                )
                .execute()
            )
            parts.append(
                GmailPart(
                    part_id=part.part_id,
                    attachment_id=part.attachment_id,
                    mime_type=part.mime_type,
                    filename=part.filename,
                    data=_decode(attachment.get("data")),
                )
            )
        return GmailMessage(
            message_id=message.message_id,
            received_at=message.received_at,
            html_bodies=message.html_bodies,
            text_bodies=message.text_bodies,
            attachments=tuple(parts),
        )
