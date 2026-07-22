from __future__ import annotations

import hashlib
import hmac
import time


class InvalidSignature(ValueError):
    pass


def content_hash(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()


def signature_payload(
    *,
    timestamp: str,
    method: str,
    path: str,
    body_hash: str,
) -> bytes:
    return "\n".join((timestamp, method.upper(), path, body_hash)).encode()


def sign_request(
    key: str,
    *,
    timestamp: str,
    method: str,
    path: str,
    body_hash: str,
) -> str:
    return hmac.new(
        key.encode(),
        signature_payload(
            timestamp=timestamp,
            method=method,
            path=path,
            body_hash=body_hash,
        ),
        hashlib.sha256,
    ).hexdigest()


def verify_request(
    key: str,
    *,
    timestamp: str,
    method: str,
    path: str,
    body_hash: str,
    signature: str,
    now: int | None = None,
    max_age_seconds: int = 300,
) -> None:
    current = now if now is not None else int(time.time())
    try:
        request_time = int(timestamp)
    except ValueError as exc:
        raise InvalidSignature("invalid timestamp") from exc
    if abs(current - request_time) > max_age_seconds:
        raise InvalidSignature("request timestamp is outside the allowed window")
    expected = sign_request(
        key,
        timestamp=timestamp,
        method=method,
        path=path,
        body_hash=body_hash,
    )
    if not hmac.compare_digest(expected, signature):
        raise InvalidSignature("request signature is invalid")
