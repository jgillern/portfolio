from __future__ import annotations

import hmac
import secrets
import time
from dataclasses import dataclass
from hashlib import sha256
from urllib.parse import urlencode

import httpx

GOOGLE_AUTHORIZATION_ENDPOINT = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_ENDPOINT = "https://oauth2.googleapis.com/token"  # noqa: S105
GMAIL_READONLY_SCOPE = "https://www.googleapis.com/auth/gmail.readonly"


class InvalidOauthState(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class GmailOauthTokens:
    refresh_token: str


class GmailOauth:
    def __init__(
        self,
        *,
        client_id: str,
        client_secret: str,
        redirect_uri: str,
        state_key: str,
    ) -> None:
        self._client_id = client_id
        self._client_secret = client_secret
        self._redirect_uri = redirect_uri
        self._state_key = state_key

    def _signature(self, expires_at: str, nonce: str) -> str:
        payload = f"{expires_at}.{nonce}".encode()
        return hmac.new(
            self._state_key.encode(),
            payload,
            sha256,
        ).hexdigest()

    def create_state(self, *, now: int | None = None) -> str:
        current = now if now is not None else int(time.time())
        expires_at = str(current + 600)
        nonce = secrets.token_urlsafe(24)
        return (
            f"{expires_at}.{nonce}."
            f"{self._signature(expires_at, nonce)}"
        )

    def verify_state(
        self,
        state: str,
        *,
        now: int | None = None,
    ) -> None:
        parts = state.split(".")
        if len(parts) != 3:
            raise InvalidOauthState("OAUTH_STATE_INVALID")
        expires_at, nonce, signature = parts
        try:
            expires = int(expires_at)
        except ValueError as exc:
            raise InvalidOauthState("OAUTH_STATE_INVALID") from exc
        current = now if now is not None else int(time.time())
        expected = self._signature(expires_at, nonce)
        if (
            expires < current
            or expires > current + 600
            or not hmac.compare_digest(signature, expected)
        ):
            raise InvalidOauthState("OAUTH_STATE_INVALID")

    def authorization_url(self, state: str) -> str:
        return GOOGLE_AUTHORIZATION_ENDPOINT + "?" + urlencode(
            {
                "client_id": self._client_id,
                "redirect_uri": self._redirect_uri,
                "response_type": "code",
                "scope": GMAIL_READONLY_SCOPE,
                "access_type": "offline",
                "prompt": "consent",
                "include_granted_scopes": "true",
                "state": state,
            }
        )

    def exchange_code(self, code: str) -> GmailOauthTokens:
        response = httpx.post(
            GOOGLE_TOKEN_ENDPOINT,
            data={
                "client_id": self._client_id,
                "client_secret": self._client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": self._redirect_uri,
            },
            timeout=20,
        )
        response.raise_for_status()
        payload = response.json()
        refresh_token = payload.get("refresh_token")
        if not isinstance(refresh_token, str) or not refresh_token:
            raise ValueError("GMAIL_REFRESH_TOKEN_MISSING")
        return GmailOauthTokens(refresh_token=refresh_token)
