from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlmodel import Session, select

from ..auth import (
    STAFF_ROLES,
    clear_session,
    current_user,
    make_magic_token,
    normalize_email,
    optional_user,
    read_magic_token,
    set_session,
    verify_password,
)
from ..db import get_session
from ..models import Role, User
from ..schemas import LoginIn, MagicLinkIn, MagicLinkOut, UserOut, VerifyIn
from ..settings import settings

router = APIRouter(prefix="/api/auth", tags=["auth"])


def user_out(u: User) -> UserOut:
    return UserOut(id=u.id, email=u.email, display_name=u.display_name or u.email.split("@")[0], role=u.role.value)


@router.get("/me", response_model=UserOut | None)
def me(user: User | None = Depends(optional_user)):
    return user_out(user) if user else None


@router.post("/magic-link", response_model=MagicLinkOut)
def magic_link(body: MagicLinkIn, session: Session = Depends(get_session)):
    email = normalize_email(body.email)
    user = session.exec(select(User).where(User.email == email)).first()
    if user is None:
        user = User(email=email, display_name=body.display_name.strip(), role=Role.player)
        session.add(user)
        session.commit()
        session.refresh(user)
    elif user.role in STAFF_ROLES:
        # Staff accounts must use their password; don't hand out links for them.
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Staff accounts sign in from the console.")
    token = make_magic_token(user.id)
    # Production would email this link. The prototype has no mail server, so in
    # dev mode the link is returned and the UI shows it as "demo mode".
    return MagicLinkOut(sent=True, dev_link=f"/auth/verify?token={token}" if settings.dev_magic_links else None)


@router.post("/verify", response_model=UserOut)
def verify(body: VerifyIn, response: Response, session: Session = Depends(get_session)):
    uid = read_magic_token(body.token)
    user = session.get(User, uid) if uid else None
    if user is None:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "This sign-in link is invalid or has expired.")
    set_session(response, user.id)
    return user_out(user)


@router.post("/login", response_model=UserOut)
def staff_login(body: LoginIn, response: Response, session: Session = Depends(get_session)):
    user = session.exec(select(User).where(User.email == body.email.strip().lower())).first()
    if user is None or user.role not in STAFF_ROLES or not verify_password(body.password, user.password_hash):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Wrong email or password.")
    set_session(response, user.id)
    return user_out(user)


@router.post("/logout", status_code=204)
def logout(response: Response, _: User = Depends(current_user)):
    clear_session(response)
