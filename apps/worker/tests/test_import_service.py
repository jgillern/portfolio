from uuid import UUID

import pytest

from portfolio_worker.import_service import ImportService
from portfolio_worker.parsers.base import ParseError


class AccountRepository:
    def __init__(self, wrapper: str) -> None:
        self.wrapper = wrapper

    def resolve_account(self, broker_code: str, account_ref: str) -> UUID:
        return UUID("00000000-0000-0000-0000-000000000001")

    def account_tax_wrapper(self, account_id: UUID) -> str:
        return self.wrapper


@pytest.mark.parametrize(
    ("broker_code", "wrapper"),
    [
        ("XTB", "DIP"),
        ("GEORGE", "STANDARD"),
    ],
)
def test_chatgpt_import_rejects_everything_except_george_dip(
    broker_code: str,
    wrapper: str,
) -> None:
    service = ImportService(AccountRepository(wrapper))  # type: ignore[arg-type]
    with pytest.raises(
        ParseError,
        match="CHATGPT_IMPORT_REQUIRES_GEORGE_DIP_PDF",
    ):
        service.import_payload(
            broker_code=broker_code,
            account_ref="synthetic-account",
            payload=b"%PDF-synthetic",
            content_type="application/pdf",
            source_channel="CHATGPT",
        )
