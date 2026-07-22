import base64
from dataclasses import dataclass

from portfolio_worker.archive import ArchivedBlob, EncryptedArchive
from portfolio_worker.crypto import SecretBox


@dataclass
class MemoryWriter:
    payload: bytes | None = None
    pathname: str | None = None

    def put(self, pathname: str, payload: bytes) -> ArchivedBlob:
        self.payload = payload
        self.pathname = pathname
        return ArchivedBlob(pathname=pathname, url="private://synthetic", size=len(payload))


def test_raw_archive_is_encrypted_before_writer_receives_it() -> None:
    writer = MemoryWriter()
    box = SecretBox(base64.b64encode(bytes(range(32))).decode())
    archive = EncryptedArchive(box=box, writer=writer)
    archive.store_raw(pathname="raw/synthetic.bin", payload=b"plain synthetic data")
    assert writer.payload is not None
    assert b"plain synthetic data" not in writer.payload
    assert (
        box.decrypt_blob(writer.payload, object_key="raw/synthetic.bin")
        == b"plain synthetic data"
    )


def test_encrypted_backup_round_trip_is_restore_verifiable() -> None:
    writer = MemoryWriter()
    box = SecretBox(base64.b64encode(bytes(range(32))).decode())
    archive = EncryptedArchive(box=box, writer=writer)
    pathname = "backups/daily/slot-1.json.gz.enc"
    tables = {
        "account": [
            {
                "id": "00000000-0000-4000-8000-000000000001",
                "pseudonym": "synthetic",
            }
        ],
        "ledger_event": [],
    }

    archive.store_backup(pathname=pathname, tables=tables)

    assert writer.payload is not None
    assert archive.decode_backup(
        pathname=pathname,
        payload=writer.payload,
    ) == tables
