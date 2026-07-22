from __future__ import annotations

from io import BytesIO

from pypdf import PdfReader

from .base import ParseError


class InvalidPdfPassword(ParseError):
    pass


def extract_pdf_text(payload: bytes, *, password: str | None = None) -> str:
    reader = PdfReader(BytesIO(payload))
    if reader.is_encrypted:
        if not password or reader.decrypt(password) == 0:
            raise InvalidPdfPassword("PASSWORD_INVALID")
    text = "\n".join(page.extract_text() or "" for page in reader.pages)
    if not text.strip():
        raise ParseError("PDF_TEXT_LAYER_MISSING")
    return text
