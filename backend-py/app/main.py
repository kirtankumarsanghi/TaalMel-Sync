from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from slowapi import Limiter, _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.util import get_remote_address

from app.api.routes import (
    auth,
    cases,
    companion,
    dashboard,
    evidence,
    exports,
    households,
    lab_reports,
    medications,
    notifications,
    prescriptions,
)
from app.auth.service import AuthError
from app.config import get_settings
from app.consent.service import AccessDenied
from app.services.evidence import EvidenceError
from app.services.medications import MedicationError
from app.services.prescriptions import PrescriptionError
from app.services.reconciliation import CaseError

limiter = Limiter(key_func=get_remote_address, default_limits=[])


def create_app() -> FastAPI:
    app = FastAPI(title="Taalmel Sync", version="0.1.0")
    app.state.limiter = limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    # The browser client runs on its own origin during development. Origins are listed
    # explicitly rather than wildcarded, because requests carry bearer tokens.
    settings = get_settings()
    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in settings.cors_origins.split(",") if o.strip()],
        allow_credentials=False,
        allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
        allow_headers=["Authorization", "Content-Type", "Idempotency-Key"],
        expose_headers=["Content-Type"],
        max_age=600,
    )

    @app.exception_handler(AuthError)
    async def _auth_error(_: Request, exc: AuthError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(AccessDenied)
    async def _access_denied(_: Request, exc: AccessDenied) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(PrescriptionError)
    async def _prescription_error(_: Request, exc: PrescriptionError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(MedicationError)
    async def _medication_error(_: Request, exc: MedicationError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(EvidenceError)
    async def _evidence_error(_: Request, exc: EvidenceError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.exception_handler(CaseError)
    async def _case_error(_: Request, exc: CaseError) -> JSONResponse:
        return JSONResponse(status_code=exc.status_code, content={"error": exc.message})

    @app.get("/health", tags=["meta"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
    app.include_router(households.router, prefix="/api", tags=["households"])
    app.include_router(prescriptions.router, prefix="/api", tags=["prescriptions"])
    app.include_router(medications.router, prefix="/api", tags=["medications"])
    app.include_router(evidence.router, prefix="/api", tags=["evidence"])
    app.include_router(cases.router, prefix="/api", tags=["cases"])
    app.include_router(notifications.router, prefix="/api", tags=["notifications"])
    app.include_router(dashboard.router, prefix="/api", tags=["dashboard"])
    app.include_router(exports.router, prefix="/api", tags=["exports"])
    app.include_router(lab_reports.router, prefix="/api", tags=["lab reports"])
    app.include_router(companion.router, prefix="/api", tags=["companion"])
    return app


app = create_app()
