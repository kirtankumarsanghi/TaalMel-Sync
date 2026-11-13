"""Time-limited public links for the doctor export.

A doctor has no account and installs nothing. A caregiver issues a short-lived token,
the patient shows it as a QR code, the doctor opens it in a browser.

Security properties:
- The token carries `typ: "doctor_export"`. Access tokens carry no such type, and this
  token is rejected by the normal auth dependency, so the two cannot be confused.
- It expires (default 2 hours, an appointment window) and is scoped to one patient.
- It grants read-only access to that patient's doctor export and nothing else.
- Issuing and every public access are audited.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt

from app.auth.service import AuthError
from app.config import get_settings

TOKEN_TYPE = "doctor_export"


@dataclass(frozen=True)
class IssuedLink:
    token: str
    url_path: str
    expires_at: datetime


def issue_token(household_member_id: str, lifetime_minutes: int | None = None) -> IssuedLink:
    settings = get_settings()
    minutes = lifetime_minutes or settings.doctor_link_minutes
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=minutes)
    token = jwt.encode(
        {
            "typ": TOKEN_TYPE,
            "sub": household_member_id,
            "jti": str(uuid4()),
            "iat": now,
            "exp": expires_at,
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    return IssuedLink(
        token=token,
        url_path=f"/api/public/doctor-export/{token}",
        expires_at=expires_at,
    )


def verify_token(token: str) -> str:
    """Returns the household_member_id the token is scoped to, or raises AuthError."""
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("This link is invalid or has expired") from exc

    if payload.get("typ") != TOKEN_TYPE:
        # A normal access token must never work here, and vice versa.
        raise AuthError("This link is invalid or has expired")

    member_id = payload.get("sub")
    if not isinstance(member_id, str):
        raise AuthError("This link is invalid or has expired")
    return member_id
