"""Reporting endpoints for the console (implemented in Phase 3)."""

from __future__ import annotations

from fastapi import APIRouter

router = APIRouter(prefix="/api/console/reports", tags=["reports"])
