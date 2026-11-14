from dataclasses import asdict
from datetime import datetime

from fastapi import APIRouter, Query, Request, Response
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from slowapi import Limiter
from slowapi.util import get_remote_address
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.audit import service as audit
from app.auth import doctor_link
from app.config import get_settings
from app.services import doctor_export as export_service
from app.services import export_html, export_pdf, qr

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
    household_member_id: str,
    format: str = Query(default="json", pattern="^(json|pdf|html)$"),
    inline: bool = Query(default=False),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
):
    result = export_service.build_export(
        session, user_id=user_id, household_member_id=household_member_id
    )
    if format == "pdf":
        pdf_bytes = export_pdf.render_pdf(result)
        disposition = "inline" if inline else "attachment"
        filename = f"taalmel-{result.patient_name.replace(' ', '-').lower()}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f'{disposition}; filename="{filename}"'},
        )
    if format == "html":
        return HTMLResponse(export_html.render_html(result))
    return _serialize(result)


@router.get("/households/{household_member_id}/info-card")
def info_card(
    household_member_id: str,
    format: str = Query(default="json", pattern="^(json|pdf)$"),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
):
    payload = export_service.build_info_card(
        session, user_id=user_id, household_member_id=household_member_id
    )
    if format == "pdf":
        return Response(
            content=export_pdf.render_info_card_pdf(payload),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="taalmel-info-card.pdf"'},
        )
    return payload


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


@router.post("/households/{household_member_id}/doctor-link/qr")
def issue_link_qr(
    household_member_id: str,
    base_url: str = Query(default="", description="Origin the doctor will open, e.g. https://app.example.com"),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> dict:
    """Issue a link and return it as a scannable QR image.

    The QR encodes the same time-limited public URL the link endpoint returns; a doctor
    scans it and the export opens, with no account and no install.
    """
    export_service.build_export(session, user_id=user_id, household_member_id=household_member_id)
    link = doctor_link.issue_token(
        household_member_id, lifetime_minutes=get_settings().doctor_link_minutes
    )
    origin = (base_url or get_settings().public_base_url).rstrip("/")
    url = f"{origin}{link.url_path}" if origin else link.url_path

    audit.log(
        session,
        audit.AuditAction.DOCTOR_LINK_ISSUED,
        user_id=user_id,
        details={"household_member_id": household_member_id, "via": "qr"},
    )
    session.commit()

    import base64

    png = qr.render_qr_png(url)
    return {
        "url": url,
        "token": link.token,
        "expires_at": link.expires_at.isoformat(),
        "qr_png_base64": base64.b64encode(png).decode("ascii"),
    }


@router.get("/households/{household_member_id}/doctor-link/qr.png")
def link_qr_png(
    household_member_id: str,
    base_url: str = Query(default=""),
    user_id: str = CurrentUserDep,
    session: Session = SessionDep,
) -> Response:
    """The QR as a raw PNG, for printing or pasting into a message."""
    export_service.build_export(session, user_id=user_id, household_member_id=household_member_id)
    link = doctor_link.issue_token(
        household_member_id, lifetime_minutes=get_settings().doctor_link_minutes
    )
    origin = (base_url or get_settings().public_base_url).rstrip("/")
    url = f"{origin}{link.url_path}" if origin else link.url_path
    return Response(content=qr.render_qr_png(url), media_type="image/png")


@router.get("/public/doctor-export/{token}")
@public_limiter.limit("30/minute")
def public_doctor_export(
    request: Request,
    token: str,
    format: str = Query(default="json", pattern="^(json|pdf|html)$"),
    session: Session = SessionDep,
):
    """No login. The token is the credential: short-lived and scoped to one patient."""
    household_member_id = doctor_link.verify_token(token)
    export = export_service.build_export_for_public(
        session, household_member_id=household_member_id
    )
    audit.log(
        session,
        audit.AuditAction.DOCTOR_EXPORT_VIEWED,
        user_id=None,
        details={"household_member_id": household_member_id, "format": format},
    )
    session.commit()

    if format == "html":
        # Rebuild as a typed export so the HTML renderer can use attributes.
        typed = export_service.build_export_without_access(session, household_member_id)
        return HTMLResponse(export_html.render_html(typed))
    if format == "pdf":
        typed = export_service.build_export_without_access(session, household_member_id)
        return Response(
            content=export_pdf.render_pdf(typed),
            media_type="application/pdf",
            headers={"Content-Disposition": 'inline; filename="taalmel-doctor-export.pdf"'},
        )
    return export
