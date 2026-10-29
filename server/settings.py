"""Runtime configuration for the platform backend, read once from the environment."""

from __future__ import annotations

import os
import warnings
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
load_dotenv(ROOT / ".env")

_DEV_SECRET = "dev-insecure-change-me"


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _bool(key: str, default: bool) -> bool:
    return _env(key, "true" if default else "false").lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Settings:
    database_url: str
    secret_key: str
    # "live" runs the real multi-agent pipeline; "mock" returns realistic answers
    # built from the KB with no LLM calls (default, so a fresh clone costs nothing).
    pipeline_mode: str
    mock_stage_delay: float
    ai_workers: int
    upload_dir: Path
    max_upload_mb: int
    # Ticket lifecycle automation
    pending_reminder_days: float
    pending_autosolve_days: float
    solved_autoclose_days: float
    lifecycle_interval_seconds: int
    # Auth
    dev_magic_links: bool
    staff_demo_password: str
    secure_cookies: bool


def load_settings() -> Settings:
    data_dir = ROOT / "data"
    secret = _env("SECRET_KEY", _DEV_SECRET)
    if secret == _DEV_SECRET:
        warnings.warn("SECRET_KEY is not set; using an insecure development key.", stacklevel=2)
    return Settings(
        database_url=_env("DATABASE_URL", f"sqlite:///{data_dir / 'everdawn.db'}"),
        secret_key=secret,
        pipeline_mode=_env("PIPELINE_MODE", "mock").lower(),
        mock_stage_delay=float(_env("MOCK_STAGE_DELAY", "0.9")),
        ai_workers=int(_env("AI_WORKERS", "2")),
        upload_dir=Path(_env("UPLOAD_DIR", str(data_dir / "uploads"))),
        max_upload_mb=int(_env("MAX_UPLOAD_MB", "8")),
        pending_reminder_days=float(_env("PENDING_REMINDER_DAYS", "3")),
        pending_autosolve_days=float(_env("PENDING_AUTOSOLVE_DAYS", "7")),
        solved_autoclose_days=float(_env("SOLVED_AUTOCLOSE_DAYS", "4")),
        lifecycle_interval_seconds=int(_env("LIFECYCLE_INTERVAL_SECONDS", "300")),
        dev_magic_links=_bool("DEV_MAGIC_LINKS", True),
        staff_demo_password=_env("STAFF_DEMO_PASSWORD", "everdawn-demo"),
        secure_cookies=_bool("SECURE_COOKIES", False),
    )


settings = load_settings()
