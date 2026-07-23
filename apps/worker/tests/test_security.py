import time

import pytest

from portfolio_worker.security import InvalidSignature, sign_request, verify_request


def test_signed_request_is_bound_to_method_path_body_and_time() -> None:
    timestamp = str(int(time.time()))
    signature = sign_request(
        "synthetic-key",
        timestamp=timestamp,
        method="POST",
        path="/api/import",
        body_hash="abc",
    )
    verify_request(
        "synthetic-key",
        timestamp=timestamp,
        method="POST",
        path="/api/import",
        body_hash="abc",
        signature=signature,
    )
    with pytest.raises(InvalidSignature):
        verify_request(
            "synthetic-key",
            timestamp=timestamp,
            method="POST",
            path="/api/import",
            body_hash="changed",
            signature=signature,
        )


def test_stale_signed_request_is_rejected() -> None:
    signature = sign_request(
        "synthetic-key",
        timestamp="100",
        method="POST",
        path="/api/import",
        body_hash="abc",
    )
    with pytest.raises(InvalidSignature):
        verify_request(
            "synthetic-key",
            timestamp="100",
            method="POST",
            path="/api/import",
            body_hash="abc",
            signature=signature,
            now=1000,
        )
