from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping, Sequence
from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum
from typing import Any

from .models import NormalizedEvent


def _decimal(value: Decimal) -> str:
    normalized = value.normalize()
    if normalized == 0:
        return "0"
    return format(normalized, "f")


def canonicalize(value: Any) -> Any:
    if isinstance(value, Decimal):
        return _decimal(value)
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {
            str(key): canonicalize(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)):
        return [canonicalize(item) for item in value]
    return value


def sha256_json(value: Any) -> str:
    payload = json.dumps(
        canonicalize(value),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def source_fingerprint(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def canonical_html_fingerprint(html: str) -> str:
    collapsed = re.sub(r"\s+", " ", html).strip().encode("utf-8")
    return source_fingerprint(collapsed)


def economic_fingerprint(event: NormalizedEvent) -> str:
    payload = event.model_dump(mode="python")
    payload["metadata"] = {
        key: value
        for key, value in event.metadata.items()
        if key not in {"gmail_message_id", "mime_part_id", "retrieved_at"}
    }
    return sha256_json(payload)
