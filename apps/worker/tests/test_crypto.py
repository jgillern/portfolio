import base64
from uuid import uuid4

import pytest

from portfolio_worker.crypto import InvalidSecret, SecretBox, SecretEnvelope


def box() -> SecretBox:
    return SecretBox(base64.b64encode(bytes(range(32))).decode())


def test_secret_round_trip_and_context_binding() -> None:
    account_id = uuid4()
    envelope = box().encrypt_secret(
        b"synthetic-password",
        account_id=account_id,
        secret_type="XTB_PDF_PASSWORD",
    )
    assert (
        box().decrypt_secret(
            envelope,
            account_id=account_id,
            secret_type="XTB_PDF_PASSWORD",
        )
        == b"synthetic-password"
    )
    with pytest.raises(InvalidSecret):
        box().decrypt_secret(
            envelope,
            account_id=uuid4(),
            secret_type="XTB_PDF_PASSWORD",
        )


@pytest.mark.parametrize("field", ["ciphertext", "nonce", "auth_tag", "aad_hash"])
def test_tampering_fails_closed(field: str) -> None:
    account_id = uuid4()
    original = box().encrypt_secret(
        b"synthetic-password",
        account_id=account_id,
        secret_type="XTB_PDF_PASSWORD",
    )
    value = bytearray(getattr(original, field))
    value[0] ^= 1
    tampered = SecretEnvelope(
        ciphertext=bytes(value) if field == "ciphertext" else original.ciphertext,
        nonce=bytes(value) if field == "nonce" else original.nonce,
        auth_tag=bytes(value) if field == "auth_tag" else original.auth_tag,
        aad_hash=bytes(value) if field == "aad_hash" else original.aad_hash,
        key_version=original.key_version,
    )
    with pytest.raises(InvalidSecret):
        box().decrypt_secret(
            tampered,
            account_id=account_id,
            secret_type="XTB_PDF_PASSWORD",
        )


def test_blob_round_trip_and_object_binding() -> None:
    encrypted = box().encrypt_blob(b"synthetic statement", object_key="raw/one")
    assert box().decrypt_blob(encrypted, object_key="raw/one") == b"synthetic statement"
    with pytest.raises(InvalidSecret):
        box().decrypt_blob(encrypted, object_key="raw/two")
