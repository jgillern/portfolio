from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Protocol
from uuid import UUID

from .archive import EncryptedArchive, VercelBlobWriter
from .config import Settings
from .crypto import SecretBox
from .providers.fx import CnbFxProvider, EcbFxProvider


class DailyPipelineError(RuntimeError):
    pass


class DailyRepository(Protocol):
    def checkpoint_job(self, job_id: UUID, checkpoint: dict[str, Any]) -> None: ...

    def finish_job(
        self,
        job_id: UUID,
        *,
        status: str,
        checkpoint: dict[str, Any],
        error_code: str | None = None,
    ) -> None: ...

    def update_connector_state(
        self,
        connector: str,
        *,
        success: bool,
        imported: int = 0,
    ) -> None: ...

    def upsert_fx_quotes(self, quotes: tuple[Any, ...]) -> int: ...

    def rebuild_position_snapshots(
        self,
        snapshot_date: date,
        reporting_currency: str,
    ) -> int: ...

    def refresh_data_quality_issues(self, snapshot_date: date) -> int: ...

    def export_backup_tables(self) -> dict[str, list[dict[str, Any]]]: ...


@dataclass(frozen=True, slots=True)
class DailyStep:
    name: str
    run: Callable[[], dict[str, Any]]


@dataclass(frozen=True, slots=True)
class DailyRunResult:
    job_id: UUID
    status: str
    checkpoint: dict[str, Any]


class DailyPipeline:
    def __init__(
        self,
        repository: DailyRepository,
        *,
        run_date: date,
        steps: Sequence[DailyStep],
    ) -> None:
        self._repository = repository
        self._run_date = run_date
        self._steps = tuple(steps)

    def run(self, job_id: UUID) -> DailyRunResult:
        checkpoint: dict[str, Any] = {
            "run_date": self._run_date.isoformat(),
            "steps": {},
        }
        for step in self._steps:
            try:
                details = step.run()
            except Exception as exc:
                checkpoint["steps"][step.name] = {
                    "status": "failed",
                    "error_type": type(exc).__name__,
                }
                self._repository.finish_job(
                    job_id,
                    status="FAILED",
                    checkpoint=checkpoint,
                    error_code="DAILY_STEP_FAILED",
                )
                raise DailyPipelineError(
                    f"daily pipeline failed at {step.name}"
                ) from exc
            checkpoint["steps"][step.name] = {
                "status": "succeeded",
                **details,
            }
            self._repository.checkpoint_job(job_id, checkpoint)

        self._repository.finish_job(
            job_id,
            status="SUCCEEDED",
            checkpoint=checkpoint,
        )
        return DailyRunResult(
            job_id=job_id,
            status="SUCCEEDED",
            checkpoint=checkpoint,
        )


def previous_business_day(run_date: date) -> date:
    candidate = run_date - timedelta(days=1)
    while candidate.weekday() >= 5:
        candidate -= timedelta(days=1)
    return candidate


def build_daily_steps(
    repository: DailyRepository,
    settings: Settings,
    *,
    run_date: date,
) -> tuple[DailyStep, ...]:
    fx_date = previous_business_day(run_date)

    def refresh_fx() -> dict[str, Any]:
        cnb_quotes = CnbFxProvider().fetch(fx_date)
        cnb_count = repository.upsert_fx_quotes(cnb_quotes)
        repository.update_connector_state(
            "CNB_FX",
            success=True,
            imported=cnb_count,
        )

        ecb_count = 0
        ecb_status = "unavailable"
        try:
            ecb_quotes = EcbFxProvider().fetch(fx_date)
        except (ValueError, OSError):
            repository.update_connector_state("ECB_FX", success=False)
        else:
            ecb_count = repository.upsert_fx_quotes(ecb_quotes)
            repository.update_connector_state(
                "ECB_FX",
                success=True,
                imported=ecb_count,
            )
            ecb_status = "succeeded"
        return {
            "rate_date": fx_date.isoformat(),
            "cnb_quotes": cnb_count,
            "ecb_quotes": ecb_count,
            "ecb_status": ecb_status,
        }

    def rebuild_snapshots() -> dict[str, Any]:
        counts = {
            currency: repository.rebuild_position_snapshots(run_date, currency)
            for currency in ("CZK", "EUR")
        }
        return {"positions": counts}

    def quality_checks() -> dict[str, Any]:
        return {
            "issues_created": repository.refresh_data_quality_issues(run_date),
        }

    def backup() -> dict[str, Any]:
        archive = EncryptedArchive(
            box=SecretBox(settings.require("master_encryption_key")),
            writer=VercelBlobWriter(token=settings.require("blob_token")),
        )
        tables = repository.export_backup_tables()
        daily_path = f"backups/daily/slot-{run_date.weekday()}.json.gz.enc"
        daily_blob = archive.store_backup(pathname=daily_path, tables=tables)
        details: dict[str, Any] = {
            "daily_path": daily_blob.pathname,
            "daily_size": daily_blob.size,
            "table_count": len(tables),
        }
        if run_date.weekday() == 6:
            weekly_slot = run_date.isocalendar().week % 4
            weekly_path = f"backups/weekly/slot-{weekly_slot}.json.gz.enc"
            weekly_blob = archive.store_backup(
                pathname=weekly_path,
                tables=tables,
            )
            details.update(
                weekly_path=weekly_blob.pathname,
                weekly_size=weekly_blob.size,
            )
        repository.update_connector_state("BACKUP", success=True, imported=1)
        return details

    return (
        DailyStep("refresh_fx", refresh_fx),
        DailyStep("rebuild_snapshots", rebuild_snapshots),
        DailyStep("quality_checks", quality_checks),
        DailyStep("encrypted_backup", backup),
    )
