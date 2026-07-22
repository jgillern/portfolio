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
    gmail_import_rules_json: str | None
    app_base_url: str | None

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
            gmail_import_rules_json=os.getenv("GMAIL_IMPORT_RULES_JSON"),
            app_base_url=os.getenv("APP_BASE_URL"),
        )

    def require(self, name: str) -> str:
        value = getattr(self, name)
        if not value:
            raise ConfigurationError(f"missing required configuration: {name}")
        return value

    def validate_production(self) -> None:
        if self.app_env != "production":
            return
        if self.app_base_url and not self.app_base_url.startswith("https://"):
            raise ConfigurationError("APP_BASE_URL must use HTTPS in production")
        if self.gmail_redirect_uri and not self.gmail_redirect_uri.startswith("https://"):
            raise ConfigurationError("GMAIL_REDIRECT_URI must use HTTPS in production")
        for name in (
            "database_write_url",
            "master_encryption_key",
            "worker_signing_key",
            "cron_secret",
            "blob_token",
            "gmail_client_id",
            "gmail_client_secret",
            "gmail_redirect_uri",
            "gmail_import_rules_json",
            "app_base_url",
        ):
            self.require(name)
