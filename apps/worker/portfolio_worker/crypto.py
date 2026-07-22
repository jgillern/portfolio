from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
from dataclasses import dataclass
from uuid import UUID

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF


class InvalidSecret(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SecretEnvelope:
    ciphertext: bytes
    nonce: bytes
    auth_tag: bytes
    aad_hash: bytes
    key_version: int


class SecretBox:
    def __init__(self, master_key_b64: str) -> None:
        try:
            master_key = base64.b64decode(master_key_b64, validate=True)
        except ValueError as exc:
            raise ValueError("master key must be valid base64") from exc
        if len(master_key) != 32:
            raise ValueError("master key must decode to exactly 32 bytes")
        self._master_key = master_key

    def _derive_key(self, purpose: str, key_version: int) -> bytes:
        if key_version < 1:
            raise ValueError("key version must be positive")
        info = f"portfolio:{purpose}:v{key_version}".encode()
        return HKDF(
            algorithm=hashes.SHA256(),
            length=32,
            salt=b"portfolio-worker-hkdf-v1",
            info=info,
        ).derive(self._master_key)

    @staticmethod
    def _aad(account_id: UUID | None, secret_type: str, key_version: int) -> bytes:
        value = {
            "account_id": str(account_id) if account_id else None,
            "key_version": key_version,
            "secret_type": secret_type,
        }
        return json.dumps(value, separators=(",", ":"), sort_keys=True).encode()

    def encrypt_secret(
        self,
        plaintext: bytes,
        *,
        account_id: UUID | None,
        secret_type: str,
        key_version: int = 1,
    ) -> SecretEnvelope:
        if not plaintext:
            raise ValueError("plaintext cannot be empty")
        aad = self._aad(account_id, secret_type, key_version)
        nonce = os.urandom(12)
        encrypted = AESGCM(self._derive_key("dynamic-secret", key_version)).encrypt(
            nonce, plaintext, aad
        )
        return SecretEnvelope(
            ciphertext=encrypted[:-16],
            nonce=nonce,
            auth_tag=encrypted[-16:],
            aad_hash=hashlib.sha256(aad).digest(),
            key_version=key_version,
        )

    def decrypt_secret(
        self,
        envelope: SecretEnvelope,
        *,
        account_id: UUID | None,
        secret_type: str,
    ) -> bytes:
        aad = self._aad(account_id, secret_type, envelope.key_version)
        if not hmac.compare_digest(hashlib.sha256(aad).digest(), envelope.aad_hash):
            raise InvalidSecret("secret context does not match")
        try:
            return AESGCM(
                self._derive_key("dynamic-secret", envelope.key_version)
            ).decrypt(
                envelope.nonce,
                envelope.ciphertext + envelope.auth_tag,
                aad,
            )
        except InvalidTag as exc:
            raise InvalidSecret("secret authentication failed") from exc

    def encrypt_blob(self, plaintext: bytes, *, object_key: str, key_version: int = 1) -> bytes:
        if not plaintext:
            raise ValueError("blob cannot be empty")
        nonce = os.urandom(12)
        aad = object_key.encode()
        encrypted = AESGCM(self._derive_key("raw-blob", key_version)).encrypt(
            nonce, plaintext, aad
        )
        return bytes([key_version]) + nonce + encrypted

    def decrypt_blob(self, payload: bytes, *, object_key: str) -> bytes:
        if len(payload) < 30:
            raise InvalidSecret("encrypted blob is truncated")
        key_version = payload[0]
        nonce = payload[1:13]
        encrypted = payload[13:]
        try:
            return AESGCM(self._derive_key("raw-blob", key_version)).decrypt(
                nonce, encrypted, object_key.encode()
            )
        except InvalidTag as exc:
            raise InvalidSecret("blob authentication failed") from exc
