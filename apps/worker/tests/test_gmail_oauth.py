import pytest

from portfolio_worker.gmail_oauth import (
    GMAIL_READONLY_SCOPE,
    GmailOauth,
    InvalidOauthState,
)


def oauth() -> GmailOauth:
    return GmailOauth(
        client_id="synthetic-client",
        client_secret="synthetic-secret",
        redirect_uri="https://worker.example.invalid/api/oauth/gmail/callback",
        state_key="synthetic-state-key-with-enough-entropy",
    )


def test_oauth_url_requests_only_read_scope_and_offline_access() -> None:
    state = oauth().create_state(now=1_000)
    url = oauth().authorization_url(state)
    assert GMAIL_READONLY_SCOPE.endswith("gmail.readonly")
    assert "scope=https%3A%2F%2Fwww.googleapis.com%2Fauth%2Fgmail.readonly" in url
    assert "access_type=offline" in url
    assert "prompt=consent" in url


def test_oauth_state_rejects_tampering_and_expiry() -> None:
    state = oauth().create_state(now=1_000)
    oauth().verify_state(state, now=1_001)
    with pytest.raises(InvalidOauthState):
        oauth().verify_state(state + "tampered", now=1_001)
    with pytest.raises(InvalidOauthState):
        oauth().verify_state(state, now=1_601)
