from __future__ import annotations

import re
import unicodedata
from datetime import datetime
from decimal import Decimal, InvalidOperation


class ParseError(ValueError):
    pass


def normalized_header(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = "".join(character for character in value if not unicodedata.combining(character))
    return re.sub(r"[^a-z0-9]+", "_", value.lower()).strip("_")


def parse_decimal(value: str) -> Decimal:
    cleaned = value.replace("\u00a0", "").replace(" ", "").strip()
    if not cleaned:
        return Decimal(0)
    if "," in cleaned and "." in cleaned:
        if cleaned.rfind(",") > cleaned.rfind("."):
            cleaned = cleaned.replace(".", "").replace(",", ".")
        else:
            cleaned = cleaned.replace(",", "")
    else:
        cleaned = cleaned.replace(",", ".")
    cleaned = cleaned.replace("%", "")
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ParseError("invalid decimal value") from exc


def parse_datetime(value: str) -> datetime:
    candidate = value.strip()
    formats = (
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%d %H:%M:%S%z",
        "%d.%m.%Y %H:%M:%S%z",
        "%d.%m.%Y %H:%M%z",
        "%d.%m.%Y %H:%M:%S",
        "%d.%m.%Y %H:%M",
        "%Y-%m-%d %H:%M:%S",
    )
    for pattern in formats:
        try:
            parsed = datetime.strptime(candidate, pattern)
            if parsed.tzinfo is None:
                from zoneinfo import ZoneInfo

                parsed = parsed.replace(tzinfo=ZoneInfo("Europe/Prague"))
            return parsed
        except ValueError:
            continue
    raise ParseError("invalid date/time value")
