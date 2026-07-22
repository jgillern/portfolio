from __future__ import annotations

import gzip
import json
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Protocol
from uuid import UUID

from .crypto import SecretBox


@dataclass(frozen=True, slots=True)
class ArchivedBlob:
    pathname: str
    url: str
    size: int


class BlobWriter(Protocol):
    def put(self, pathname: str, payload: bytes) -> ArchivedBlob: ...


class VercelBlobWriter:
    def __init__(self, *, token: str) -> None:
        from vercel.blob import BlobClient

        self._client = BlobClient(token=token)

    def put(self, pathname: str, payload: bytes) -> ArchivedBlob:
        result = self._client.put(
            pathname,
            payload,
            access="private",
            content_type="application/octet-stream",
            add_random_suffix=False,
        )
        return ArchivedBlob(
            pathname=result.pathname,
            url=result.url,
            size=len(payload),
        )


def _json_default(value: Any) -> Any:
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, bytes):
        import base64

        return {"base64": base64.b64encode(value).decode()}
    raise TypeError(f"unsupported backup value: {type(value).__name__}")


class EncryptedArchive:
    def __init__(self, *, box: SecretBox, writer: BlobWriter) -> None:
        self._box = box
        self._writer = writer

    def store_raw(self, *, pathname: str, payload: bytes) -> ArchivedBlob:
        encrypted = self._box.encrypt_blob(payload, object_key=pathname)
        return self._writer.put(pathname, encrypted)

    def store_backup(
        self,
        *,
        pathname: str,
        tables: dict[str, list[dict[str, Any]]],
    ) -> ArchivedBlob:
        serialized = json.dumps(
            tables,
            default=_json_default,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode()
        compressed = gzip.compress(serialized, compresslevel=9, mtime=0)
        encrypted = self._box.encrypt_blob(compressed, object_key=pathname)
        return self._writer.put(pathname, encrypted)

    def decode_backup(
        self,
        *,
        pathname: str,
        payload: bytes,
    ) -> dict[str, list[dict[str, Any]]]:
        compressed = self._box.decrypt_blob(payload, object_key=pathname)
        decoded = json.loads(gzip.decompress(compressed))
        if not isinstance(decoded, dict):
            raise ValueError("backup root must be an object")
        for table_name, rows in decoded.items():
            if not isinstance(table_name, str) or not isinstance(rows, list):
                raise ValueError("backup table payload is malformed")
            if not all(isinstance(row, dict) for row in rows):
                raise ValueError("backup rows must be objects")
        return decoded
