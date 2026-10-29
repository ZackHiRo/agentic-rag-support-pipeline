"""FastAPI app for the Everdawn support platform.

Run (dev):   uvicorn server.main:app --reload
The React app (web/) talks to /api; in production its build (web/dist) is
served by this same process, so the whole platform is one container.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlmodel import Session

from .auth import ensure_demo_staff
from .db import engine, init_db
from .kb import get_catalog
from .routers import auth, console, help, reports
from .services import lifecycle
from .services.events import broker
from .services.jobs import recover_interrupted_runs, wait_idle
from .settings import ROOT, settings

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("everdawn")

WEB_DIST = ROOT / "web" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    init_db()
    with Session(engine) as s:
        ensure_demo_staff(s)
    get_catalog()
    broker.bind(asyncio.get_running_loop())
    recover_interrupted_runs()
    log.info("pipeline mode: %s", settings.pipeline_mode)
    sweeper = asyncio.create_task(lifecycle.run_forever()) if settings.lifecycle_interval_seconds > 0 else None
    yield
    if sweeper:
        sweeper.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await sweeper
    await asyncio.to_thread(wait_idle, 10)


app = FastAPI(title="Everdawn Support Platform", version="0.1.0", lifespan=lifespan)
app.include_router(auth.router)
app.include_router(help.router)
app.include_router(console.router)
app.include_router(reports.router)


@app.get("/api/health", tags=["meta"])
def health():
    return {"ok": True, "pipeline_mode": settings.pipeline_mode}


if WEB_DIST.exists():
    app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """Serve the SPA: real files from web/dist, everything else gets index.html."""
        if path == "api" or path.startswith("api/"):
            raise HTTPException(404, "Not found")
        candidate = (WEB_DIST / path).resolve()
        if path and candidate.is_file() and WEB_DIST.resolve() in candidate.parents:
            return FileResponse(candidate)
        return FileResponse(WEB_DIST / "index.html")
