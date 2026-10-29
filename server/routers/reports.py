"""Reporting endpoint for the console dashboard."""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlmodel import Session

from ..auth import current_staff
from ..db import get_session
from ..models import User
from ..services.reports import build_report

router = APIRouter(prefix="/api/console/reports", tags=["reports"])


@router.get("")
def report(
    days: int = Query(default=30, ge=1, le=180),
    session: Session = Depends(get_session),
    _: User = Depends(current_staff),
) -> dict:
    return build_report(session, days)
