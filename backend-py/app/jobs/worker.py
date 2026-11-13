"""ARQ worker entry point. Start with: uv run arq app.jobs.worker.WorkerSettings"""

from typing import Any

from arq.connections import RedisSettings

from app.config import get_settings
from app.db.session import get_engine
from app.ocr.provider import get_ocr_provider
from app.services.prescriptions import run_ocr_job
from app.services.storage import get_storage
from sqlmodel import Session


async def run_ocr(ctx: dict[str, Any], prescription_id: str) -> None:
    with Session(get_engine()) as session:
        run_ocr_job(
            session,
            storage=get_storage(),
            provider=get_ocr_provider(),
            prescription_id=prescription_id,
        )


class WorkerSettings:
    functions = [run_ocr]
    redis_settings = RedisSettings.from_dsn(get_settings().redis_url)
    max_tries = 3
