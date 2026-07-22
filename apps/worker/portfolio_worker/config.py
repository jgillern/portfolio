from __future__ import annotations

import os
from dataclasses import dataclass


class ConfigurationError(RuntimeError):
    pass


@dataclass(frozen=True, slots=True)
class Settings:
    app_env: str
    database_write_url: str | None
    master_encryption_key: str | None
    worker_signing_key: str | None
    cron_secret: str | None
    blob_token: str | None
    gmail_client_id: str | None
    gmail_client_secret: str | None
    gmail_redirect_uri: str | None

    @classmethod
    def from_env(cls) -> Settings:
        return cls(
            app_env=os.getenv("APP_ENV", "development"),
            database_write_url=os.getenv("DATABASE_WRITE_URL"),
            master_encryption_key=os.getenv("MASTER_ENCRYPTION_KEY"),
            worker_signing_key=os.getenv("WORKER_SIGNING_KEY"),
            cron_secret=os.getenv("CRON_SECRET"),
            blob_token=os.getenv("BLOB_READ_WRITE_TOKEN"),
            gmail_client_id=os.getenv("GMAIL_CLIENT_ID"),
            gmail_client_secret=os.getenv("GMAIL_CLIENT_SECRET"),
            gmail_redirect_uri=os.getenv("GMAIL_REDIRECT_URI"),
        )

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise ConfigurationError(f"missing required configuration: {name}")
        return value

    def validate_production(self) -> None:
        if self.app_env != "production":
            return
        for name in (
            "database_write_url",
            "master_encryption_key",
            "worker_signing_key",
            "cron_secret",
        ):
            self.require(name)
