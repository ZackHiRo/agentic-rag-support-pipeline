"""Authentication: signed session cookies, passwordless player sign-in, staff passwords.

Players sign in with an emailed magic link. There is no mail server in the
prototype, so with DEV_MAGIC_LINKS=true the link is returned to the browser
instead (the UI labels this clearly as demo mode). Staff sign in with a
password; demo staff accounts are created at startup.
"""

from __future__ import annotations

import hashlib
import hmac
import secrets

from fastapi import Depends, HTTPException, Request, Response, status
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer
from sqlmodel import Session, select

from .db import get_session
from .models import Role, User
from .settings import settings

SESSION_COOKIE = "evd_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days
MAGIC_MAX_AGE = 60 * 15  # 15 minutes

_serializer = URLSafeTimedSerializer(settings.secret_key)

STAFF_ROLES = (Role.agent, Role.admin)
DEMO_STAFF = (
    ("agent@everdawn.dev", "Sam Rivera", Role.agent),
    ("lead@everdawn.dev", "Jordan Lee", Role.agent),
    ("admin@everdawn.dev", "Morgan Chen", Role.admin),
)


# --- Passwords (stdlib scrypt) -------------------------------------------------


def hash_password(password: str) -> str:
    salt = secrets.token_bytes(16)
    digest = hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1)
    return f"scrypt${salt.hex()}${digest.hex()}"


def verify_password(password: str, stored: str | None) -> bool:
    if not stored or not stored.startswith("scrypt$"):
        return False
    _, salt_hex, digest_hex = stored.split("$", 2)
    digest = hashlib.scrypt(password.encode(), salt=bytes.fromhex(salt_hex), n=2**14, r=8, p=1)
    return hmac.compare_digest(digest.hex(), digest_hex)


# --- Tokens and cookies ------------------------------------------------------------


def make_magic_token(user_id: int) -> str:
    return _serializer.dumps({"uid": user_id}, salt="magic-link")


def read_magic_token(token: str) -> int | None:
    try:
        data = _serializer.loads(token, salt="magic-link", max_age=MAGIC_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return int(data["uid"])


def set_session(response: Response, user_id: int) -> None:
    response.set_cookie(
        SESSION_COOKIE,
        _serializer.dumps({"uid": user_id}, salt="session"),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=settings.secure_cookies,
    )


def clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def _session_user_id(request: Request) -> int | None:
    raw = request.cookies.get(SESSION_COOKIE)
    if not raw:
        return None
    try:
        data = _serializer.loads(raw, salt="session", max_age=SESSION_MAX_AGE)
    except (BadSignature, SignatureExpired):
        return None
    return int(data["uid"])


# --- Dependencies ------------------------------------------------------------------


def optional_user(request: Request, session: Session = Depends(get_session)) -> User | None:
    uid = _session_user_id(request)
    return session.get(User, uid) if uid else None


def current_user(user: User | None = Depends(optional_user)) -> User:
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Sign in to continue.")
    return user


def current_staff(user: User = Depends(current_user)) -> User:
    if user.role not in STAFF_ROLES:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Support staff only.")
    return user


def normalize_email(email: str) -> str:
    email = email.strip().lower()
    if "@" not in email or email.startswith("@") or email.endswith("@"):
        raise HTTPException(422, "Enter a valid email address.")
    return email


def ensure_demo_staff(session: Session) -> None:
    for email, name, role in DEMO_STAFF:
        if session.exec(select(User).where(User.email == email)).first() is None:
            session.add(
                User(
                    email=email,
                    display_name=name,
                    role=role,
                    password_hash=hash_password(settings.staff_demo_password),
                )
            )
    session.commit()
