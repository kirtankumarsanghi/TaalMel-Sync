"""Authentication: argon2 password hashing, JWT access tokens, rotating refresh tokens.

Refresh tokens are stored hashed (SHA-256). Each login starts a token "family".
Presenting an already-revoked refresh token is treated as reuse: the whole
family is revoked, because the token has likely leaked.
"""

import hashlib
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import jwt
from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from sqlmodel import Session, select

from app.config import get_settings
from app.db.models import RefreshToken, User

_hasher = PasswordHasher()


class AuthError(Exception):
    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


@dataclass(frozen=True)
class TokenPair:
    access_token: str
    refresh_token: str


def hash_password(password: str) -> str:
    return _hasher.hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    try:
        return _hasher.verify(password_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def _hash_refresh(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()


def _utcnow() -> datetime:
    return datetime.now(UTC)


TOKEN_TYPE = "access"


def decode_access_token(token: str) -> dict:
    settings = get_settings()
    try:
        payload = jwt.decode(token, settings.jwt_secret, algorithms=[settings.jwt_algorithm])
    except jwt.PyJWTError as exc:
        raise AuthError("Invalid or expired token") from exc

    # A doctor-export link is signed with the same secret but is not a login token.
    # Requiring the type means the two can never be used interchangeably.
    if payload.get("typ") != TOKEN_TYPE:
        raise AuthError("Invalid or expired token")
    return payload


def _issue_pair(session: Session, user: User, family: str | None = None) -> TokenPair:
    settings = get_settings()
    now = _utcnow()
    access = jwt.encode(
        {
            "typ": TOKEN_TYPE,
            "sub": user.id,
            "role": user.role,
            "name": user.name,
            "iat": now,
            "exp": now + timedelta(minutes=settings.access_token_minutes),
        },
        settings.jwt_secret,
        algorithm=settings.jwt_algorithm,
    )
    raw_refresh = str(uuid4())
    session.add(
        RefreshToken(
            token_hash=_hash_refresh(raw_refresh),
            user_id=user.id,
            family=family or str(uuid4()),
            expires_at=now + timedelta(days=settings.refresh_token_days),
            created_at=now,
        )
    )
    return TokenPair(access_token=access, refresh_token=raw_refresh)


def register(session: Session, *, name: str, phone: str, password: str, role: str) -> tuple[User, TokenPair]:
    if session.exec(select(User).where(User.phone == phone)).first():
        raise AuthError("Phone number already registered", status_code=409)
    user = User(role=role, name=name, phone=phone, password_hash=hash_password(password))
    session.add(user)
    session.flush()
    tokens = _issue_pair(session, user)
    session.commit()
    return user, tokens


def login(session: Session, *, phone: str, password: str) -> tuple[User, TokenPair]:
    user = session.exec(select(User).where(User.phone == phone)).first()
    if user is None or not verify_password(user.password_hash, password):
        raise AuthError("Invalid credentials")
    tokens = _issue_pair(session, user)
    session.commit()
    return user, tokens


def refresh(session: Session, raw_refresh: str) -> tuple[User, TokenPair]:
    stored = session.exec(
        select(RefreshToken).where(RefreshToken.token_hash == _hash_refresh(raw_refresh))
    ).first()
    if stored is None:
        raise AuthError("Invalid refresh token")

    if stored.revoked_at is not None:
        # Reuse of a rotated token: revoke the whole family.
        now = _utcnow()
        for token in session.exec(
            select(RefreshToken).where(RefreshToken.family == stored.family)
        ).all():
            if token.revoked_at is None:
                token.revoked_at = now
                session.add(token)
        session.commit()
        raise AuthError("Refresh token reuse detected")

    if _as_utc(stored.expires_at) < _utcnow():
        raise AuthError("Refresh token expired")

    stored.revoked_at = _utcnow()
    session.add(stored)
    user = session.get(User, stored.user_id)
    if user is None:
        raise AuthError("Invalid refresh token")
    tokens = _issue_pair(session, user, family=stored.family)
    session.commit()
    return user, tokens


def logout(session: Session, user_id: str) -> None:
    now = _utcnow()
    for token in session.exec(
        select(RefreshToken).where(RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None))  # type: ignore[union-attr]
    ).all():
        token.revoked_at = now
        session.add(token)
    session.commit()


def _as_utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)
