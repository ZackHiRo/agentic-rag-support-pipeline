from server.services.routing import RunSignals, decide


def test_clean_answer_waits_for_player_confirmation():
    d = decide(RunSignals(trigger="intake", qa_passed=True, confidence="high"))
    assert (d.kind, d.status, d.send_to_player, d.needs_human, d.needs_review) == ("answered", "pending", True, False, False)


def test_missing_info_becomes_checklist():
    d = decide(RunSignals(trigger="intake", missing_info=("Share your ID", " "), qa_passed=True))
    assert d.kind == "needs_info"
    assert d.status == "pending"
    assert d.action_items == ["Share your ID"]


def test_low_confidence_still_answers_but_flags_review():
    for sig in (
        RunSignals(trigger="intake", confidence="low", qa_passed=True),
        RunSignals(trigger="player_reply", confidence="high", qa_passed=False),
    ):
        d = decide(sig)
        assert d.send_to_player and d.needs_review and not d.needs_human


def test_legal_escalation_is_high_priority_holding_reply():
    d = decide(RunSignals(trigger="intake", escalation_flag=True, threat_type="legal", missing_info=("x",)))
    assert d.kind == "escalated"
    assert d.send_to_player and d.needs_human
    assert (d.status, d.priority, d.handoff_reason) == ("open", "high", "safety")
    assert d.action_items == []  # never ask an escalated player for homework
    assert not d.crisis_resources


def test_self_harm_is_urgent_with_crisis_resources():
    d = decide(RunSignals(trigger="intake", threat_type="rlt_self_harm"))
    assert d.priority == "urgent"
    assert d.crisis_resources


def test_threat_type_alone_escalates_even_without_flag():
    assert decide(RunSignals(trigger="intake", threat_type="rlt_violence")).priority == "urgent"


def test_agent_drafts_are_never_sent():
    d = decide(RunSignals(trigger="agent_draft", escalation_flag=True, missing_info=("x",)))
    assert d.kind == "draft" and not d.send_to_player and d.status is None


def test_broker_delivers_events_published_from_worker_threads():
    import asyncio
    import threading

    from server.services.events import Broker

    async def scenario():
        b = Broker()
        b.bind(asyncio.get_running_loop())
        async with b.subscribe("ticket:1") as q:
            threading.Thread(target=b.publish, args=("ticket:1", {"type": "run.stage", "key": "qa"})).start()
            return await asyncio.wait_for(q.get(), timeout=2)

    assert asyncio.run(scenario())["key"] == "qa"
