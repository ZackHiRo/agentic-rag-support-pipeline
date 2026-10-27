"""Support agent entry point — multi-agent pipeline orchestration.

Public API (unchanged from v1):
    run_agent(ticket, images=None, guidance="") -> AgentRun

No OpenAI client is created here. All LLM calls go through provider-agnostic
adapters from src/config.py. To switch providers, set env vars — no code change.
"""

from __future__ import annotations

import concurrent.futures
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

from .agents.orchestrator import PipelineRun, StageTimings, run_pipeline
from .agents.safety import run_safety
from .config import config_summary, get_classifier_adapter
from .retrieve import Hit, get_retriever
from .schemas import (
    AgentOutput,
    ClassifierOutput,
    QAResult,
    SafetyOutput,
)
from .vision import transcribe_screenshots

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

RETRIEVE_TOP_K  = int(__import__("os").getenv("RETRIEVE_TOP_K",  "8"))
RETRIEVE_FINAL_K = int(__import__("os").getenv("RETRIEVE_FINAL_K", "6"))
ROLE_BOOST_ARTICLES = int(__import__("os").getenv("ROLE_BOOST_ARTICLES", "2"))

ROLE_HEADING_PATTERNS = [
    "investigat", "procedur", "information to", "escalat",
    "gather", "what to ask", "questions to", "how to handle",
    "handling", "decision", "next steps", "action",
]


# ---------------------------------------------------------------------------
# Backward-compatible AgentRun (v1 fields + v2 extensions)
# ---------------------------------------------------------------------------

@dataclass
class AgentRun:
    # v1 fields — UI reads these directly
    output: AgentOutput
    classification: ClassifierOutput
    hits: list[Hit]
    screenshot_text: str = ""
    guidance: str = ""

    # v2 fields — new UI panels
    safety: SafetyOutput | None = None
    pipeline_run: PipelineRun | None = None
    qa_results: list[QAResult] = field(default_factory=list)
    retry_count: int = 0
    timings: StageTimings = field(default_factory=StageTimings)


# ---------------------------------------------------------------------------
# Classifier (uses config adapter — provider-agnostic)
# ---------------------------------------------------------------------------

CLASSIFIER_SYSTEM = (
    "You classify incoming Everdawn support tickets for a support "
    "knowledge base retriever. Be concise and faithful. Produce 2-3 short "
    "search queries (5-12 words each) covering the main angles of the ticket "
    "(e.g. issue type, specific feature/error, platform). Do not invent facts "
    "the ticket does not state."
)


def classify_ticket(ticket: str, guidance: str = "") -> ClassifierOutput:
    adapter = get_classifier_adapter()
    user = ticket
    if guidance.strip():
        user = (
            f"Ticket text:\n{ticket}\n\n"
            "Human reviewer guidance (treat as additional ticket context "
            "when picking topics and search queries):\n"
            f"{guidance.strip()}"
        )
    try:
        return adapter.parse(
            messages=[
                {"role": "system", "content": CLASSIFIER_SYSTEM},
                {"role": "user", "content": user},
            ],
            response_format=ClassifierOutput,
            temperature=0.0,
        )
    except Exception:
        return ClassifierOutput(primary_topic="unknown", search_queries=[ticket[:300]])


# ---------------------------------------------------------------------------
# Retrieval (unchanged — no LLM, pure vector/BM25)
# ---------------------------------------------------------------------------

def gather_hits(classification: ClassifierOutput, ticket: str) -> list[Hit]:
    retriever = get_retriever()
    queries = list(classification.search_queries or [])
    queries.append(" ".join(ticket.strip().splitlines())[:500])

    primary = retriever.multi_search(queries, k=RETRIEVE_FINAL_K, top_k=RETRIEVE_TOP_K)

    seen: set[str] = {h.chunk_id for h in primary}
    if classification.is_bug_report:
        for hit in retriever.multi_search(queries, k=2, top_k=RETRIEVE_TOP_K, where={"type": "known-issue"}):
            if hit.chunk_id not in seen:
                primary.append(hit)
                seen.add(hit.chunk_id)

    top_article_ids: list[str] = []
    for hit in primary:
        aid = str((hit.metadata or {}).get("article_id") or "")
        if aid and aid not in top_article_ids:
            top_article_ids.append(aid)
        if len(top_article_ids) >= ROLE_BOOST_ARTICLES:
            break
    for aid in top_article_ids:
        for rh in retriever.fetch_article_sections(aid, ROLE_HEADING_PATTERNS):
            if rh.chunk_id not in seen:
                primary.append(rh)
                seen.add(rh.chunk_id)

    return _group_by_article(primary)


def _group_by_article(hits: list[Hit]) -> list[Hit]:
    best_score: dict[str, float] = {}
    first_seen: dict[str, int] = {}
    groups: dict[str, list[Hit]] = {}
    for idx, hit in enumerate(hits):
        aid = str((hit.metadata or {}).get("article_id") or hit.chunk_id)
        groups.setdefault(aid, []).append(hit)
        best_score[aid] = max(best_score.get(aid, -1.0), hit.score)
        first_seen.setdefault(aid, idx)
    return [
        h
        for aid in sorted(groups, key=lambda a: (-best_score[a], first_seen[a]))
        for h in groups[aid]
    ]


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def run_agent(
    ticket: str,
    images: list[bytes] | None = None,
    guidance: str = "",
    on_stage: Callable[[str], None] | None = None,
    persona: str = "human_agent",
) -> AgentRun:
    """End-to-end multi-agent pass. Provider-agnostic — no OpenAI imports here.

    ``on_stage`` is called with a short human-readable label as each stage
    starts, so callers can show live progress. ``persona`` selects how the
    player reply is written: "human_agent" (a draft for a human to send) or
    "ai_assistant" (sent directly to the player, discloses it is an AI).
    """
    report = on_stage or (lambda _label: None)
    images = images or []
    typed = ticket.strip()
    if not typed and not images:
        raise ValueError("Provide either ticket text or at least one screenshot.")

    timings = StageTimings()

    # Stage 1: Vision
    t0 = time.perf_counter()
    if images:
        report(f"Reading {len(images)} screenshot(s)...")
    screenshot_text = transcribe_screenshots(images) if images else ""
    timings.vision = time.perf_counter() - t0

    if screenshot_text:
        composed = (
            "[Attached screenshots transcribed verbatim by the vision model. "
            "Treat the text below as part of the ticket evidence; PII rules still apply.]\n"
            f"{screenshot_text}\n[End attached screenshots]\n"
        )
        composed = f"{composed}\n{typed}" if typed else composed
    else:
        composed = typed

    guidance_clean = guidance.strip()

    # Stage 2: Classify
    report("Classifying ticket...")
    t0 = time.perf_counter()
    classification = classify_ticket(composed, guidance_clean)
    timings.classifier = time.perf_counter() - t0

    # Stages 3-4: Retrieval and Safety are independent — run them concurrently.
    report("Retrieving SOP context and running safety analysis...")

    def _timed(fn, *args):
        t = time.perf_counter()
        result = fn(*args)
        return result, time.perf_counter() - t

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as ex:
        fut_hits = ex.submit(_timed, gather_hits, classification, composed)
        fut_safety = ex.submit(_timed, run_safety, composed, classification)
        hits, timings.retrieval = fut_hits.result()
        safety, timings.safety = fut_safety.result()

    # Stages 5-6: Parallel drafting + QA loop
    pipeline = run_pipeline(
        ticket=composed,
        classification=classification,
        safety=safety,
        hits=hits,
        guidance=guidance_clean,
        screenshot_text=screenshot_text,
        timings=timings,
        on_stage=report,
        persona=persona,
    )

    return AgentRun(
        output=pipeline.output,
        classification=classification,
        hits=pipeline.hits,
        screenshot_text=screenshot_text,
        guidance=guidance_clean,
        safety=safety,
        pipeline_run=pipeline,
        qa_results=pipeline.qa_results,
        retry_count=pipeline.retry_count,
        timings=timings,
    )
