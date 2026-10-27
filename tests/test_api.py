from datetime import timedelta

import pytest
from sqlmodel import Session, select

from server.db import engine, utcnow
from server.models import Ticket
from server.services import lifecycle, pipeline
from server.services.jobs import wait_idle
from server.settings import settings

from .conftest import open_ticket


# --- Help center ---------------------------------------------------------------------


def test_suggestions_match_partial_words(app_client):
    slugs = [a["slug"] for a in app_client.get("/api/kb/suggest", params={"q": "matchmak error 105"}).json()]
    assert slugs[0] == "matchmaking-error-105"
    assert app_client.get("/api/kb/suggest", params={"q": "ab"}).json() == []


def test_internal_sops_are_never_public(app_client):
    public = {a["slug"] for a in app_client.get("/api/kb/articles").json()}
    assert "connection-issues" not in public  # internal SOP in kb/demo
    assert app_client.get("/api/kb/articles/connection-issues").status_code == 404
    assert app_client.get("/api/kb/articles/fix-connection-issues").status_code == 200


# --- Ticket lifecycle -------------------------------------------------------------------


def test_ai_answers_and_player_confirms(player):
    t = open_ticket(player, "Matchmaking Error 105 when my PC and PS5 friends queue together")
    assert t["status"] == "pending" and t["ai_state"] == "idle"
    ai = t["messages"][-1]
    assert ai["author_kind"] == "ai"
    assert "AI helper" in ai["body"] and "Alex" not in ai["body"]
    assert [c["slug"] for c in ai["citations"]] == ["matchmaking-error-105"]
    # Internal SOPs and the AI's internal note must not reach the player.
    assert all(m["visibility"] == "public" for m in t["messages"])
    assert "macro" not in ai["body"].lower()

    t = player.post(f"/api/tickets/{t['ref']}/resolve").json()
    assert t["status"] == "solved" and t["resolved_by"] == "ai"
    assert player.post(f"/api/tickets/{t['ref']}/csat", json={"rating": 5}).json()["csat"] == 5


def test_checklist_then_ai_answers_again(player):
    t = open_ticket(player, "Please help me recover my account, I lost access to my email")
    assert t["status"] == "pending"
    (action,) = t["actions"]
    assert "NovaStar ID" in action["text"]

    r = player.post(f"/api/tickets/{t['ref']}/actions/{action['id']}/complete", data={"response": "EVD-1234-ABCD-5678"})
    assert r.status_code == 200, r.text
    wait_idle()
    t = player.get(f"/api/tickets/{t['ref']}").json()
    assert t["actions"][0]["done"]
    assert [m["author_kind"] for m in t["messages"]] == ["player", "ai", "player", "ai"]
    assert t["status"] == "pending"  # answered again, waiting for confirmation


def test_legal_threat_escalates_to_humans(player, staff):
    t = open_ticket(player, "If this isn't fixed I'm contacting my lawyer and will sue NovaStar")
    assert t["status"] == "open" and t["needs_human"]
    assert t["priority"] == "high" and t["handoff_reason"] == "safety"
    assert t["actions"] == []
    queue = staff.get("/api/console/tickets", params={"view": "attention"}).json()
    assert t["ref"] in [row["ref"] for row in queue["tickets"]]


def test_self_harm_is_urgent_and_shows_crisis_resources(player):
    t = open_ticket(player, "I lost everything in the game and honestly I want to hurt myself")
    assert t["priority"] == "urgent"
    assert t["messages"][-1]["crisis_resources"] is True


def test_handoff_stops_the_ai(player):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    t = player.post(f"/api/tickets/{t['ref']}/need-human", json={"reason": "The workaround didn't work"}).json()
    assert t["status"] == "open" and t["needs_human"]
    n = len(t["messages"])
    player.post(f"/api/tickets/{t['ref']}/messages", data={"body": "Any update?"})
    wait_idle()
    t = player.get(f"/api/tickets/{t['ref']}").json()
    assert len(t["messages"]) == n + 1  # just the player's message; the AI stayed quiet
    assert t["status"] == "open"


def test_player_reply_reopens_and_ai_answers(player):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    player.post(f"/api/tickets/{t['ref']}/resolve")
    player.post(f"/api/tickets/{t['ref']}/messages", data={"body": "It came back after the patch"})
    wait_idle()
    t = player.get(f"/api/tickets/{t['ref']}").json()
    assert t["status"] == "pending"
    assert t["messages"][-1]["author_kind"] == "ai"


def test_ai_failure_hands_off(player, monkeypatch):
    def boom(*_a, **_k):
        raise RuntimeError("provider down")

    monkeypatch.setattr("server.services.jobs.run_pipeline", boom)
    t = open_ticket(player, "Something odd happened")
    assert t["status"] == "open" and t["needs_human"] and t["ai_state"] == "failed"
    assert t["messages"][-1]["author_kind"] == "system"


def test_players_only_see_their_own_tickets(player, app_client):
    t = open_ticket(player, "Matchmaking error 105")
    other = app_client.__class__(app_client.app)
    link = other.post("/api/auth/magic-link", json={"email": "someone-else@example.com"}).json()["dev_link"]
    other.post("/api/auth/verify", json={"token": link.split("token=", 1)[1]})
    assert other.get(f"/api/tickets/{t['ref']}").status_code == 404
    assert other.post(f"/api/tickets/{t['ref']}/resolve").status_code == 404


def test_rejects_unsupported_uploads(player):
    r = player.post(
        "/api/tickets",
        data={"description": "see attached"},
        files={"files": ("virus.exe", b"MZ", "application/x-msdownload")},
    )
    assert r.status_code == 415


def test_screenshot_upload_is_stored_and_served(player):
    png = b"\x89PNG\r\n\x1a\n" + b"0" * 32
    r = player.post("/api/tickets", data={"description": ""}, files={"files": ("error.png", png, "image/png")})
    assert r.status_code == 201, r.text
    wait_idle()
    t = player.get(f"/api/tickets/{r.json()['ref']}").json()
    (att,) = t["messages"][0]["attachments"]
    assert player.get(att["url"]).content == png


# --- Console ------------------------------------------------------------------------------


def test_console_requires_staff(player):
    assert player.get("/api/console/tickets").status_code == 403


def test_staff_reply_takes_over_and_requests_items(player, staff):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    detail = staff.get(f"/api/console/tickets/{t['id']}").json()
    assert any(m["visibility"] == "internal" for m in detail["messages"])  # AI internal note
    assert detail["runs"][0]["result"]["output"]["next_steps"]

    r = staff.post(
        f"/api/console/tickets/{t['id']}/reply",
        json={"body": "Hi! Could you send your network log?", "action_items": ["Attach NetLog.txt"]},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["status"] == "pending" and d["needs_human"] and d["first_human_response_at"]
    assert d["assignee_name"] == "Sam Rivera"

    t = player.get(f"/api/tickets/{t['ref']}").json()
    assert t["messages"][-1]["author_kind"] == "agent"
    assert [a["text"] for a in t["actions"] if not a["done"]] == ["Attach NetLog.txt"]


def test_internal_notes_stay_internal(player, staff):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    staff.post(f"/api/console/tickets/{t['id']}/reply", json={"body": "Probably a dupe of EVD-1001", "visibility": "internal"})
    bodies = [m["body"] for m in player.get(f"/api/tickets/{t['ref']}").json()["messages"]]
    assert not any("dupe" in b for b in bodies)


def test_ai_draft_is_not_sent(player, staff):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    n = len(player.get(f"/api/tickets/{t['ref']}").json()["messages"])
    assert staff.post(f"/api/console/tickets/{t['id']}/ai-draft", json={"guidance": "be brief"}).status_code == 202
    wait_idle()
    d = staff.get(f"/api/console/tickets/{t['id']}").json()
    assert d["runs"][0]["trigger"] == "agent_draft" and d["runs"][0]["status"] == "succeeded"
    assert "This is Sam from the Everdawn team" in d["runs"][0]["result"]["output"]["player_reply"]  # signed by the requesting agent
    assert len(player.get(f"/api/tickets/{t['ref']}").json()["messages"]) == n


def test_console_views_and_patch(player, staff):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    me = next(s for s in staff.get("/api/console/staff").json() if s["email"] == "agent@everdawn.dev")
    d = staff.patch(f"/api/console/tickets/{t['id']}", json={"status": "on_hold", "priority": "high", "assignee_id": me["id"]}).json()
    assert (d["status"], d["priority"], d["assignee_id"]) == ("on_hold", "high", me["id"])
    kinds = [e["kind"] for e in d["events"]]
    assert {"status.changed", "priority.changed", "assignee.changed"} <= set(kinds)
    listing = staff.get("/api/console/tickets", params={"view": "mine"}).json()
    assert t["id"] in [row["id"] for row in listing["tickets"]]
    assert listing["counts"]["on_hold"] >= 1
    assert staff.get("/api/console/tickets", params={"view": "bogus"}).status_code == 422


# --- Lifecycle automation -----------------------------------------------------------------------


def _age(ticket_id: int, **fields_days_ago: float) -> None:
    with Session(engine) as s:
        t = s.get(Ticket, ticket_id)
        for name, days in fields_days_ago.items():
            setattr(t, name, utcnow() - timedelta(days=days))
        s.commit()


@pytest.mark.parametrize("days_pending, expected_status, reminded", [(1, "pending", False), (3.5, "pending", True), (8, "solved", False)])
def test_pending_reminders_and_autosolve(player, days_pending, expected_status, reminded):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    _age(t["id"], pending_since=days_pending)
    lifecycle.sweep()
    t = player.get(f"/api/tickets/{t['ref']}").json()
    assert t["status"] == expected_status
    assert (t["messages"][-1]["author_kind"] == "system") is reminded
    if expected_status == "solved":
        assert t["resolved_by"] == "auto"


def test_solved_tickets_auto_close(player):
    t = open_ticket(player, "Matchmaking error 105 on PC")
    player.post(f"/api/tickets/{t['ref']}/resolve")
    _age(t["id"], solved_at=settings.solved_autoclose_days + 1)
    lifecycle.sweep()
    t = player.get(f"/api/tickets/{t['ref']}").json()
    assert t["status"] == "closed"
    assert t["resolved_by"] == "ai"  # closing must keep who resolved it (reporting depends on it)
    assert player.post(f"/api/tickets/{t['ref']}/messages", data={"body": "hello?"}).status_code == 409


def test_stage_keys_map_pipeline_labels():
    assert pipeline.stage_key("Reading 2 screenshot(s)...") == "vision"
    assert pipeline.stage_key("QA validation (retry 1)...") == "qa"
    assert pipeline.stage_key("Something new") == "other"


# --- Reporting and demo data ------------------------------------------------------------------------


def test_reports_are_staff_only_and_reflect_activity(player, staff):
    assert player.get("/api/console/reports").status_code == 403
    before = staff.get("/api/console/reports", params={"days": 7}).json()["kpis"]
    t = open_ticket(player, "Matchmaking error 105 on PC")
    player.post(f"/api/tickets/{t['ref']}/resolve")
    r = staff.get("/api/console/reports", params={"days": 7}).json()
    assert r["kpis"]["tickets"] == before["tickets"] + 1
    assert r["kpis"]["resolved_by"]["ai"] == before["resolved_by"]["ai"] + 1
    assert len(r["volume"]) == 7
    assert {"topics", "kb_gaps", "pending_aging", "qa", "latency", "top_articles"} <= r.keys()


def test_seed_creates_and_resets_only_demo_data(player):
    from server.seed import reset_demo, seed

    mine = open_ticket(player, "Matchmaking error 105 on PC")
    seed(tickets=25, days=10)
    with Session(engine) as s:
        demo = s.exec(select(Ticket).where(Ticket.demo == True)).all()  # noqa: E712
        assert len(demo) == 25
        assert all(t.ref and t.created_at for t in demo)
        assert reset_demo(s) == 25
        assert s.get(Ticket, mine["id"]) is not None  # real tickets survive a reset
