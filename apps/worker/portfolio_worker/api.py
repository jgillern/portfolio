from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from pydantic import BaseModel, Field

from .config import ConfigurationError, Settings
from .crypto import SecretBox
from .import_service import ImportService
from .repository import RepositoryError, WorkerRepository
from .security import InvalidSignature, content_hash, verify_request

app = FastAPI(
    title="Portfolio worker",
    version="0.1.0",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)


def _settings() -> Settings:
    settings = Settings.from_env()
    settings.validate_production()
    return settings


def _repository() -> WorkerRepository:
    return WorkerRepository(_settings().require("database_write_url"))


def _verify_cron(authorization: str | None) -> None:
    expected = "Bearer " + _settings().require("cron_secret")
    if not authorization or not hmac.compare_digest(authorization, expected):
        raise HTTPException(status_code=401, detail="unauthorized")


def _verify_signed_request(
    request: Request,
    *,
    body_hash: str,
    timestamp: str | None,
    signature: str | None,
) -> None:
    if not timestamp or not signature:
        raise HTTPException(status_code=401, detail="missing request signature")
    try:
        verify_request(
            _settings().require("worker_signing_key"),
            timestamp=timestamp,
            method=request.method,
            path=request.url.path,
            body_hash=body_hash,
            signature=signature,
        )
    except InvalidSignature as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc


@app.get("/api/health")
def health() -> dict[str, str]:
    try:
        _settings().validate_production()
    except ConfigurationError:
        return {"status": "degraded", "service": "portfolio-worker"}
    return {"status": "ok", "service": "portfolio-worker"}


@app.get("/api/cron/daily")
def daily_cron(authorization: str | None = Header(default=None)) -> dict[str, str | bool]:
    _verify_cron(authorization)
    key = datetime.now(UTC).date().isoformat()
    try:
        job_id, created = _repository().start_job("DAILY", f"daily:{key}")
    except RepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return {"job_id": str(job_id), "started": created}


@app.post("/api/import")
async def import_document(
    request: Request,
    broker_code: Annotated[str, Form()],
    account_ref: Annotated[str, Form()],
    document: Annotated[UploadFile, File()],
    x_portfolio_timestamp: str | None = Header(default=None),
    x_portfolio_signature: str | None = Header(default=None),
    x_portfolio_content_sha256: str | None = Header(default=None),
) -> dict[str, str | int | bool]:
    payload = await document.read()
    actual_hash = content_hash(payload)
    if not x_portfolio_content_sha256 or not hmac.compare_digest(
        actual_hash, x_portfolio_content_sha256
    ):
        raise HTTPException(status_code=400, detail="content hash mismatch")
    _verify_signed_request(
        request,
        body_hash=actual_hash,
        timestamp=x_portfolio_timestamp,
        signature=x_portfolio_signature,
    )
    try:
        result = ImportService(_repository()).import_payload(
            broker_code=broker_code,
            account_ref=account_ref,
            payload=payload,
            content_type=document.content_type or "application/octet-stream",
        )
    except (ValueError, RepositoryError) as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    return {
        "raw_import_id": result.raw_import_id,
        "accepted": result.accepted,
        "duplicates": result.duplicates,
        "duplicate_document": result.duplicate_document,
    }


class SecretInput(BaseModel):
    account_id: UUID | None = None
    secret_type: str = Field(pattern=r"^(GMAIL_REFRESH_TOKEN|XTB_PDF_PASSWORD)$")
    value: str = Field(min_length=1, max_length=4096)
    key_version: int = Field(default=1, ge=1)


@app.post("/api/secrets")
async def store_secret(
    request: Request,
    secret: SecretInput,
    x_portfolio_timestamp: str | None = Header(default=None),
    x_portfolio_signature: str | None = Header(default=None),
) -> dict[str, str]:
    body = await request.body()
    _verify_signed_request(
        request,
        body_hash=hashlib.sha256(body).hexdigest(),
        timestamp=x_portfolio_timestamp,
        signature=x_portfolio_signature,
    )
    settings = _settings()
    envelope = SecretBox(settings.require("master_encryption_key")).encrypt_secret(
        secret.value.encode(),
        account_id=secret.account_id,
        secret_type=secret.secret_type,
        key_version=secret.key_version,
    )
    secret_id = _repository().store_secret(
        account_id=secret.account_id,
        secret_type=secret.secret_type,
        ciphertext=envelope.ciphertext,
        nonce=envelope.nonce,
        auth_tag=envelope.auth_tag,
        aad_hash=envelope.aad_hash,
        key_version=envelope.key_version,
    )
    return {"secret_id": str(secret_id)}
