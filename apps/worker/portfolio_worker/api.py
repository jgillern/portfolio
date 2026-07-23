from __future__ import annotations

import hashlib
import hmac
from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import FastAPI, File, Form, Header, HTTPException, Request, UploadFile
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field

from .archive import EncryptedArchive, VercelBlobWriter
from .config import ConfigurationError, Settings
from .crypto import InvalidSecret, SecretBox
from .daily import DailyPipeline, DailyPipelineError, build_daily_steps
from .gmail_oauth import GmailOauth, InvalidOauthState
from .import_service import ImportService
from .models import SecretKind
from .repository import RepositoryError, WorkerRepository
from .security import InvalidSignature, content_hash, verify_request

MAX_UPLOAD_BYTES = 10 * 1024 * 1024


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


def _archive() -> EncryptedArchive:
    settings = _settings()
    return EncryptedArchive(
        box=SecretBox(settings.require("master_encryption_key")),
        writer=VercelBlobWriter(token=settings.require("blob_token")),
    )


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


def _run_daily(*, idempotency_key: str) -> dict[str, str | bool]:
    repository = _repository()
    run_date = datetime.now(UTC).date()
    try:
        job_id, created = repository.start_job("DAILY", idempotency_key)
    except RepositoryError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if not created:
        return {"job_id": str(job_id), "started": False, "status": "duplicate"}
    try:
        result = DailyPipeline(
            repository,
            run_date=run_date,
            steps=build_daily_steps(
                repository,
                _settings(),
                run_date=run_date,
            ),
        ).run(job_id)
    except DailyPipelineError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return {
        "job_id": str(job_id),
        "started": True,
        "status": result.status.lower(),
    }


@app.get("/api/cron/daily")
def daily_cron(authorization: str | None = Header(default=None)) -> dict[str, str | bool]:
    _verify_cron(authorization)
    key = datetime.now(UTC).date().isoformat()
    return _run_daily(idempotency_key=f"daily:{key}")


@app.post("/api/sync")
async def manual_sync(
    request: Request,
    x_portfolio_timestamp: str | None = Header(default=None),
    x_portfolio_signature: str | None = Header(default=None),
    x_portfolio_idempotency_key: str | None = Header(default=None),
) -> dict[str, str | bool]:
    body = await request.body()
    _verify_signed_request(
        request,
        body_hash=hashlib.sha256(body).hexdigest(),
        timestamp=x_portfolio_timestamp,
        signature=x_portfolio_signature,
    )
    key = x_portfolio_idempotency_key or x_portfolio_timestamp
    if not key or len(key) > 128:
        raise HTTPException(status_code=400, detail="invalid idempotency key")
    return _run_daily(idempotency_key=f"manual:{key}")


@app.post("/api/import")
async def import_document(
    request: Request,
    broker_code: Annotated[str, Form()],
    account_ref: Annotated[str, Form()],
    document: Annotated[UploadFile, File()],
    source_channel: Annotated[
        Literal["UPLOAD", "CHATGPT"],
        Form(),
    ] = "UPLOAD",
    x_portfolio_timestamp: str | None = Header(default=None),
    x_portfolio_signature: str | None = Header(default=None),
    x_portfolio_content_sha256: str | None = Header(default=None),
) -> dict[str, str | int | bool]:
    payload = await document.read()
    if not payload or len(payload) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="invalid document size")
    broker = broker_code.upper()
    content_type = document.content_type or "application/octet-stream"
    if source_channel == "CHATGPT" and (
        broker != "GEORGE" or content_type != "application/pdf"
    ):
        raise HTTPException(
            status_code=400,
            detail="CHATGPT_IMPORT_REQUIRES_GEORGE_PDF",
        )
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
    repository = _repository()
    pdf_password = None
    pdf_secret = {
        "XTB": SecretKind.XTB_PDF,
        "GEORGE": SecretKind.GEORGE_PDF,
    }.get(broker)
    if pdf_secret is not None and content_type == "application/pdf":
        account_id = repository.resolve_account(broker, account_ref)
        try:
            secret_id, envelope = repository.load_active_secret(
                account_id=account_id,
                secret_type=pdf_secret.value,
            )
        except RepositoryError as exc:
            raise HTTPException(
                status_code=422,
                detail="PDF_PASSWORD_NOT_CONFIGURED",
            ) from exc
        try:
            pdf_password = SecretBox(
                _settings().require("master_encryption_key")
            ).decrypt_secret(
                envelope,
                account_id=account_id,
                secret_type=pdf_secret.value,
            ).decode()
        except (InvalidSecret, UnicodeDecodeError) as exc:
            repository.audit_secret_access(secret_id, outcome="FAILED")
            raise HTTPException(
                status_code=422,
                detail="PASSWORD_INVALID",
            ) from exc
        repository.audit_secret_access(secret_id, outcome="SUCCESS")
    try:
        result = ImportService(repository, archive=_archive()).import_payload(
            broker_code=broker,
            account_ref=account_ref,
            payload=payload,
            content_type=content_type,
            source_channel=source_channel,
            pdf_password=pdf_password,
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
    secret_type: str = Field(
        pattern=r"^(GMAIL_REFRESH_TOKEN|XTB_PDF_PASSWORD|GEORGE_PDF_PASSWORD)$"
    )
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


def _gmail_oauth() -> GmailOauth:
    settings = _settings()
    return GmailOauth(
        client_id=settings.require("gmail_client_id"),
        client_secret=settings.require("gmail_client_secret"),
        redirect_uri=settings.require("gmail_redirect_uri"),
        state_key=settings.require("worker_signing_key"),
    )


@app.post("/api/oauth/gmail/start")
async def gmail_oauth_start(
    request: Request,
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
    oauth = _gmail_oauth()
    state = oauth.create_state()
    return {"authorization_url": oauth.authorization_url(state)}


@app.get("/api/oauth/gmail/callback")
def gmail_oauth_callback(
    code: str,
    state: str,
) -> RedirectResponse:
    oauth = _gmail_oauth()
    try:
        oauth.verify_state(state)
        tokens = oauth.exchange_code(code)
    except (InvalidOauthState, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail="GMAIL_OAUTH_FAILED",
        ) from exc
    settings = _settings()
    envelope = SecretBox(
        settings.require("master_encryption_key")
    ).encrypt_secret(
        tokens.refresh_token.encode(),
        account_id=None,
        secret_type=SecretKind.GMAIL_REFRESH.value,
        key_version=1,
    )
    _repository().store_secret(
        account_id=None,
        secret_type=SecretKind.GMAIL_REFRESH.value,
        ciphertext=envelope.ciphertext,
        nonce=envelope.nonce,
        auth_tag=envelope.auth_tag,
        aad_hash=envelope.aad_hash,
        key_version=envelope.key_version,
    )
    target = settings.require("app_base_url").rstrip("/")
    return RedirectResponse(
        url=target + "/sources?gmail=connected",
        status_code=303,
    )
