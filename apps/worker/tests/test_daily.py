from datetime import date
from uuid import UUID

import pytest

from portfolio_worker.daily import (
    DailyPipeline,
    DailyPipelineError,
    DailyStep,
    previous_business_day,
)


class FakeRepository:
    def __init__(self) -> None:
        self.checkpoints: list[dict] = []
        self.finished: tuple[str, dict, str | None] | None = None

    def checkpoint_job(self, _job_id: UUID, checkpoint: dict) -> None:
        self.checkpoints.append(
            {
                "run_date": checkpoint["run_date"],
                "steps": dict(checkpoint["steps"]),
            }
        )

    def finish_job(
        self,
        _job_id: UUID,
        *,
        status: str,
        checkpoint: dict,
        error_code: str | None = None,
    ) -> None:
        self.finished = (status, checkpoint, error_code)


def test_daily_pipeline_checkpoints_each_step_and_finishes() -> None:
    repository = FakeRepository()
    pipeline = DailyPipeline(
        repository,
        run_date=date(2026, 7, 22),
        steps=(
            DailyStep("one", lambda: {"count": 1}),
            DailyStep("two", lambda: {"count": 2}),
        ),
    )
    result = pipeline.run(UUID("00000000-0000-4000-8000-000000000001"))
    assert result.status == "SUCCEEDED"
    assert len(repository.checkpoints) == 2
    assert repository.finished is not None
    assert repository.finished[0] == "SUCCEEDED"


def test_daily_pipeline_records_only_redacted_error_type() -> None:
    repository = FakeRepository()

    def fail() -> dict:
        raise RuntimeError("secret must never enter the checkpoint")

    pipeline = DailyPipeline(
        repository,
        run_date=date(2026, 7, 22),
        steps=(DailyStep("sensitive", fail),),
    )
    with pytest.raises(DailyPipelineError, match="sensitive"):
        pipeline.run(UUID("00000000-0000-4000-8000-000000000001"))
    assert repository.finished is not None
    checkpoint = repository.finished[1]
    assert checkpoint["steps"]["sensitive"] == {
        "status": "failed",
        "error_type": "RuntimeError",
    }
    assert "secret" not in str(checkpoint)


def test_previous_business_day_skips_weekend() -> None:
    assert previous_business_day(date(2026, 7, 20)) == date(2026, 7, 17)
