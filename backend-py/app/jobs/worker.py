"""ARQ worker entry point. Start with: uv run arq app.jobs.worker.WorkerSettings"""

from typing import Any

from arq import cron
from arq.connections import RedisSettings
from sqlmodel import Session

from app.config import get_settings
from app.db.session import get_engine
from app.ocr.provider import get_ocr_provider
from app.services.notifications_delivery import deliver_pending
from app.services.prescriptions import run_ocr_job
from app.services.storage import get_storage
from app.services.triggers import run_all_periodic_checks


async def run_ocr(ctx: dict[str, Any], prescription_id: str) -> None:
    with Session(get_engine()) as session:
        run_ocr_job(
            session,
            storage=get_storage(),
            provider=get_ocr_provider(),
            prescription_id=prescription_id,
        )


async def run_daily_checks(ctx: dict[str, Any]) -> int:
    with Session(get_engine()) as session:
        created = run_all_periodic_checks(session)
        deliver_pending(session)
        return created


class WorkerSettings:
    functions = [run_ocr, run_daily_checks]
    cron_jobs = [cron(run_daily_checks, hour=8, minute=0)]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
