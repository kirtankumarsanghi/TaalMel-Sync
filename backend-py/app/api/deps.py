from collections.abc import Iterator

from fastapi import Depends, Header
from sqlmodel import Session

from app.auth.service import AuthError, decode_access_token
from app.db.session import get_session


def db_session() -> Iterator[Session]:
    yield from get_session()


def _decode(authorization: str | None) -> dict:
    if not authorization or not authorization.startswith("Bearer "):
        raise AuthError("Missing bearer token")
    payload = decode_access_token(authorization.removeprefix("Bearer ").strip())
    if not isinstance(payload.get("sub"), str):
        raise AuthError("Invalid or expired token")
    return payload


def current_user_id(authorization: str | None = Header(default=None)) -> str:
    return _decode(authorization)["sub"]


def current_user_role(authorization: str | None = Header(default=None)) -> str:
    return str(_decode(authorization).get("role", ""))


SessionDep = Depends(db_session)
CurrentUserDep = Depends(current_user_id)
CurrentRoleDep = Depends(current_user_role)
