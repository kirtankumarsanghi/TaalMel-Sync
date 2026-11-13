from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Request
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.audit import service as audit
from app.auth import doctor_link
from app.config import get_settings
from app.services import doctor_export as export_service

router = APIRouter()
public_limiter = Limiter(key_func=get_remote_address)


class IssuedLinkOut(BaseModel):
    token: str
    url_path: str
    expires_at: datetime


def _serialize(result: export_service.DoctorExport) -> dict:
    data = asdict(result)
    data["generated_at"] = result.generated_at.isoformat()
    for med in data["medications"]:
        if med["prescribed_on"] is not None:
            med["prescribed_on"] = med["prescribed_on"].isoformat()
        for entry in med["timeline"]:
            entry["date"] = entry["date"].isoformat()
    return data


@router.get("/households/{household_member_id}/doctor-export")
def doctor_export(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> dict:
    return _serialize(
        export_service.build_export(
            session, user_id=user_id, household_member_id=household_member_id
        )
    )


@router.get("/households/{household_member_id}/info-card")
def info_card(
    household_member_id: str, user_id: str = CurrentUserDep, session: Session = SessionDep
) -> dict:
    return export_service.build_info_card(
        session, user_id=user_id, household_member_id=household_member_id
    )


@router.post("/households/{household_member_id}/doctor-link", response_model=IssuedLinkOut)
def issue_link(
    household_member_id: str,
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> IssuedLinkOut:
    # Issuing requires the same access as reading the export.
    export_service.build_export(session, user_id=user_id, household_member_id=household_member_id)
    link = doctor_link.issue_token(
        household_member_id, lifetime_minutes=get_settings().doctor_link_minutes
    )
    audit.log(
        session,
        audit.AuditAction.DOCTOR_LINK_ISSUED,
        user_id=user_id,
        details={"household_member_id": household_member_id, "expires_at": link.expires_at.isoformat()},
    )
    session.commit()
    return IssuedLinkOut(token=link.token, url_path=link.url_path, expires_at=link.expires_at)


@router.get("/public/doctor-export/{token}")
@public_limiter.limit("30/minute")
def public_doctor_export(request: Request, token: str, session: Session = SessionDep) -> dict:
    """No login. The token is the credential: short-lived and scoped to one patient."""
    household_member_id = doctor_link.verify_token(token)
    export = export_service.build_export_for_public(
        session, household_member_id=household_member_id
    )
    audit.log(
        session,
        audit.AuditAction.DOCTOR_EXPORT_VIEWED,
        user_id=None,
        details={"household_member_id": household_member_id},
    )
    session.commit()
    return export
