"""Attachment storage on local disk (data/uploads/<ticket id>/)."""

from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import HTTPException, UploadFile, status
from sqlmodel import Session

from .models import Attachment, Message, Ticket
from .settings import settings

# Screenshots, plus plain-text logs (e.g. NetLog.txt) that support asks players for.
ALLOWED = {
    "image/png": ".png",
    "image/jpeg": ".jpg",
    "image/webp": ".webp",
    "image/gif": ".gif",
    "text/plain": ".txt",
}
MAX_FILES = 6


def save_uploads(session: Session, ticket: Ticket, message: Message, files: list[UploadFile] | None) -> list[Attachment]:
    files = [f for f in (files or []) if f and f.filename]
    if len(files) > MAX_FILES:
        raise HTTPException(422, f"Attach at most {MAX_FILES} files.")
    limit = settings.max_upload_mb * 1024 * 1024
    folder = settings.upload_dir / str(ticket.id)
    saved: list[Attachment] = []
    for f in files:
        mime = (f.content_type or "").split(";")[0].strip().lower()
        if mime == "application/octet-stream" and f.filename.lower().endswith((".txt", ".log")):
            mime = "text/plain"
        if mime not in ALLOWED:
            raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, f"{f.filename}: only images and .txt/.log files are supported.")
        data = f.file.read(limit + 1)
        if len(data) > limit:
            raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{f.filename} is larger than {settings.max_upload_mb} MB.")
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{uuid.uuid4().hex}{ALLOWED[mime]}"
        path.write_bytes(data)
        att = Attachment(
            ticket_id=ticket.id, message_id=message.id, filename=Path(f.filename).name[:200],
            mime=mime, size=len(data), path=str(path),
        )
        session.add(att)
        saved.append(att)
    return saved
