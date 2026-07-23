from io import BytesIO

import pytest
from pypdf import PdfWriter

from portfolio_worker.parsers.base import ParseError
from portfolio_worker.parsers.pdf import InvalidPdfPassword, extract_pdf_text


def encrypted_empty_pdf(password: str) -> bytes:
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.encrypt(password)
    writer.write(output)
    return output.getvalue()


def test_invalid_pdf_password_has_safe_error_code() -> None:
    payload = encrypted_empty_pdf("synthetic-password")
    with pytest.raises(InvalidPdfPassword, match="PASSWORD_INVALID"):
        extract_pdf_text(payload, password="wrong")


def test_pdf_without_text_layer_requests_explicit_fallback() -> None:
    payload = encrypted_empty_pdf("synthetic-password")
    with pytest.raises(ParseError, match="PDF_TEXT_LAYER_MISSING"):
        extract_pdf_text(payload, password="synthetic-password")
