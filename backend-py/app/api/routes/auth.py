from fastapi import APIRouter, Request
from pydantic import BaseModel, ConfigDict, Field
from sqlmodel import Session

from app.api.deps import CurrentUserDep, SessionDep
from app.audit import service as audit
from app.auth import service as auth_service
from app.auth.ratelimit import login_limiter
from app.auth.service import AuthError
from app.config import get_settings
from app.db.models import User

router = APIRouter()


class RegisterIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    name: str = Field(min_length=1, max_length=120)
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=8, max_length=256)
    role: str = Field(pattern="^(caregiver|patient)$")


class LoginIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    phone: str = Field(min_length=6, max_length=20)
    password: str = Field(min_length=1, max_length=256)


class RefreshIn(BaseModel):
    model_config = ConfigDict(extra="forbid")
    refresh_token: str = Field(min_length=1)


class UserOut(BaseModel):
    id: str
    role: str
    name: str
    phone: str | None


class TokenOut(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    user: UserOut


def _user_out(user: User) -> UserOut:
    return UserOut(id=user.id, role=user.role, name=user.name, phone=user.phone)


def _token_out(user: User, tokens: auth_service.TokenPair) -> TokenOut:
    return TokenOut(
        access_token=tokens.access_token,
        refresh_token=tokens.refresh_token,
        user=_user_out(user),
    )


@router.post("/register", response_model=TokenOut, status_code=201)
def register(body: RegisterIn, session: Session = SessionDep) -> TokenOut:
    user, tokens = auth_service.register(
        session, name=body.name, phone=body.phone, password=body.password, role=body.role
    )
    audit.log(session, audit.AuditAction.REGISTER, user_id=user.id)
    session.commit()
    return _token_out(user, tokens)


@router.post("/login", response_model=TokenOut)
@login_limiter.limit(get_settings().login_rate_limit)
def login(request: Request, body: LoginIn, session: Session = SessionDep) -> TokenOut:
    try:
        user, tokens = auth_service.login(session, phone=body.phone, password=body.password)
    except AuthError:
        audit.log(session, audit.AuditAction.LOGIN_FAILED, user_id=None, details={"phone_suffix": body.phone[-4:]})
        session.commit()
        raise
    audit.log(session, audit.AuditAction.LOGIN, user_id=user.id)
    session.commit()
    return _token_out(user, tokens)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, session: Session = SessionDep) -> TokenOut:
    user, tokens = auth_service.refresh(session, body.refresh_token)
    return _token_out(user, tokens)


@router.post("/logout", status_code=204)
def logout(user_id: str = CurrentUserDep, session: Session = SessionDep) -> None:
    auth_service.logout(session, user_id)
    audit.log(session, audit.AuditAction.LOGOUT, user_id=user_id)
    session.commit()


@router.get("/me", response_model=UserOut)
def me(user_id: str = CurrentUserDep, session: Session = SessionDep) -> UserOut:
    user = session.get(User, user_id)
    if user is None:
        raise AuthError("User not found", status_code=404)
    return _user_out(user)
