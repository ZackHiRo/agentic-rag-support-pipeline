"""Test setup: isolated temp database, mock pipeline, no API keys, no delays.

Environment must be set before any `server.*` import, because settings are read
at import time.
"""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

_TMP = Path(tempfile.mkdtemp(prefix="everdawn-tests-"))
os.environ.update(
    {
        "DATABASE_URL": f"sqlite:///{_TMP / 'test.db'}",
        "UPLOAD_DIR": str(_TMP / "uploads"),
        "PIPELINE_MODE": "mock",
        "MOCK_STAGE_DELAY": "0",
        "SECRET_KEY": "test-secret",
        "LIFECYCLE_INTERVAL_SECONDS": "0",
        "OPENAI_API_KEY": "",
        "ANTHROPIC_API_KEY": "",
    }
)
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import itertools  # noqa: E402

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from server.main import app  # noqa: E402
from server.services.jobs import wait_idle  # noqa: E402

_ids = itertools.count(1)


@pytest.fixture(scope="session")
def app_client():
    with TestClient(app) as c:
        yield c


def _new_client() -> TestClient:
    c = TestClient(app)
    return c


@pytest.fixture
def player(app_client):
    """A freshly signed-in player with their own cookie jar."""
    c = _new_client()
    email = f"player{next(_ids)}@example.com"
    link = c.post("/api/auth/magic-link", json={"email": email}).json()["dev_link"]
    r = c.post("/api/auth/verify", json={"token": link.split("token=", 1)[1]})
    assert r.status_code == 200, r.text
    return c


@pytest.fixture
def staff(app_client):
    c = _new_client()
    r = c.post("/api/auth/login", json={"email": "agent@everdawn.dev", "password": "everdawn-demo"})
    assert r.status_code == 200, r.text
    return c


def open_ticket(client: TestClient, description: str, **form) -> dict:
    r = client.post("/api/tickets", data={"description": description, **form})
    assert r.status_code == 201, r.text
    wait_idle()
    return client.get(f"/api/tickets/{r.json()['ref']}").json()
