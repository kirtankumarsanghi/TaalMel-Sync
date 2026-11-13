"""Job queue adapters. The service depends only on `enqueue_ocr(prescription_id)`.

- InlineQueue: runs the OCR job immediately in the same process. Used for dev and tests.
- ArqQueue: enqueues to Redis for the ARQ worker. Used in deployment.
"""

from collections.abc import Callable

from sqlmodel import Session

from app.ocr.base import OcrProvider
from app.services.prescriptions import run_ocr_job
from app.services.storage import StorageService


class InlineQueue:
    """Runs OCR synchronously. A failed job re-raises so the caller sees the error."""

    def __init__(
        self,
        session_factory: Callable[[], Session],
        storage: StorageService,
        provider: OcrProvider,
    ) -> None:
        self._session_factory = session_factory
        self._storage = storage
        self._provider = provider

    def enqueue_ocr(self, prescription_id: str) -> None:
        with self._session_factory() as session:
            run_ocr_job(
                session,
                storage=self._storage,
                provider=self._provider,
                prescription_id=prescription_id,
            )


class ArqQueue:
    """Enqueues the OCR job to Redis. Requires the `arq` worker process to be running."""

    def __init__(self, redis_url: str) -> None:
        self._redis_url = redis_url

    def enqueue_ocr(self, prescription_id: str) -> None:
        import asyncio

        from arq import create_pool
        from arq.connections import RedisSettings

        async def _enqueue() -> None:
            pool = await create_pool(RedisSettings.from_dsn(self._redis_url))
            try:
                await pool.enqueue_job("run_ocr", prescription_id)
            finally:
                await pool.close()

        asyncio.run(_enqueue())
