"""Streamlit UI for the Everdawn support agent (multi-agent v2).

Run with:
    streamlit run app.py

Workflow:
  1. Paste the ticket text in the text area (and optionally attach screenshots).
  2. Click "Draft response".
  3. Three tabs render: Player Reply, Internal Note, Next Steps.
     Each has a native copy-to-clipboard button (top-right of the code box).
  4. QA panel shows the overall score, per-check breakdown, and retry info.
  5. Sources expander shows which SOP sections were used.
"""

from __future__ import annotations

import hashlib
import io
import os
import sys
import time
import traceback
from pathlib import Path

import streamlit as st
from dotenv import load_dotenv
from streamlit_paste_button import paste_image_button

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")
sys.path.insert(0, str(ROOT))

from src.agent import run_agent  # noqa: E402
from src.config import config_summary  # noqa: E402
from src.schemas import AgentOutput, ClassifierOutput  # noqa: E402

st.set_page_config(
    page_title="Everdawn Support Agent",
    layout="wide",
    page_icon=":video_game:",
)

CONFIDENCE_BADGE = {"high": "🟢 High", "medium": "🟡 Medium", "low": "🔴 Low"}
SEVERITY_ICON = {"critical": "🚨", "major": "⚠️", "minor": "💬"}


# --- Cached helpers --------------------------------------------------------


@st.cache_resource(show_spinner=False)
def _chroma_collection():
    import chromadb
    from chromadb.config import Settings

    client = chromadb.PersistentClient(
        path=str(ROOT / os.getenv("CHROMA_DIR", ".chroma")),
        settings=Settings(anonymized_telemetry=False),
    )
    return client.get_or_create_collection("support_kb")


@st.cache_data(ttl=60, show_spinner=False)
def kb_stats() -> dict:
    kb = ROOT / "kb"
    md_files = [p for p in kb.rglob("*.md") if not p.name.startswith("_")] if kb.exists() else []
    try:
        chunk_count = _chroma_collection().count()
    except Exception:
        chunk_count = None
    return {"articles": len(md_files), "chunks": chunk_count}


def missing_api_keys(cfg: dict[str, str]) -> list[str]:
    """Return the env vars the active config needs but that are unset.

    Embeddings always go through OpenAI, so OPENAI_API_KEY is always required;
    ANTHROPIC_API_KEY is required only if some role runs on Anthropic.
    """
    providers = {model.split(":", 1)[0] for model in cfg.values()}
    needed = ["OPENAI_API_KEY"]
    if "anthropic" in providers:
        needed.append("ANTHROPIC_API_KEY")
    return [k for k in needed if not os.getenv(k, "").strip()]


def _reset_inputs() -> None:
    """on_click callback for Clear: runs before widgets render, so it can reset them."""
    st.session_state["ticket_input"] = ""
    st.session_state["ticket_guidance"] = ""
    st.session_state["pasted_images"] = []
    # Keep ticket_last_paste_hash: the paste component keeps returning its last
    # image, and forgetting the hash would re-add it on the next rerun.
    st.session_state.pop("last_run", None)
    st.session_state.pop("last_wall_time", None)
    # A file_uploader can't be cleared directly; a new key gives a fresh widget.
    st.session_state["uploader_nonce"] = st.session_state.get("uploader_nonce", 0) + 1


def _remove_pasted(index: int) -> None:
    st.session_state["pasted_images"].pop(index)


st.session_state.setdefault("pasted_images", [])
st.session_state.setdefault("uploader_nonce", 0)


# --- Sidebar --------------------------------------------------------------

try:
    cfg = config_summary()
    cfg_error = None
except Exception as e:
    cfg, cfg_error = {}, e

missing_keys = missing_api_keys(cfg) if cfg else []

with st.sidebar:
    st.header("Everdawn Support Agent")
    st.caption("Multi-agent RAG pipeline over game support SOPs.")

    stats = kb_stats()
    m1, m2 = st.columns(2)
    m1.metric("Articles", stats["articles"])
    m2.metric("Chunks", stats["chunks"] if stats["chunks"] is not None else "—")
    if stats["chunks"] == 0:
        st.warning("The index is empty. Run `python -m src.ingest` first.")

    if cfg_error:
        st.warning(f"Could not load model config: {cfg_error}")
    elif missing_keys:
        st.error(f"Missing in `.env`: {', '.join(f'`{k}`' for k in missing_keys)}")
    else:
        st.success("API keys configured.")

    with st.expander("Models", expanded=False):
        for role, model_id in cfg.items():
            st.markdown(f"**{role}:** `{model_id}`")
        st.markdown(f"**Embeddings:** `{os.getenv('OPENAI_EMBED_MODEL', 'text-embedding-3-small')}`")
        if "ollama" in {m.split(":", 1)[0] for m in cfg.values()}:
            st.caption(f"Ollama endpoint: `{os.getenv('LLM_BASE_URL', 'http://localhost:11434/v1')}`")

    with st.expander("Pipeline stages", expanded=False):
        st.markdown(
            "1. Vision → screenshot transcription  \n"
            "2. Classifier → topic/flags/queries  \n"
            "3. Retrieval ∥ **Safety** (concurrent)  \n"
            "4. **Note + Reply + Steps** (parallel)  \n"
            "5. **QA** → score + targeted retries"
        )

    with st.expander("Maintenance commands", expanded=False):
        st.code(
            "python -m src.html_to_md      # re-convert HTML -> markdown\n"
            "python -m src.build_prompts   # rebuild tone/process prompt bundles\n"
            "python -m src.ingest          # (re)embed kb/ into Chroma\n"
            "python -m src.ingest --force  # re-embed everything",
            language="bash",
        )


# --- Input pane -----------------------------------------------------------

st.title("Ticket triage")
st.caption(
    "Paste a ticket and click **Draft response**. The pipeline produces a "
    "player-facing reply, an internal note, and next investigation steps, "
    "with a QA score and cited SOP sections."
)

input_col, side_col = st.columns([3, 2], gap="large")

with input_col:
    ticket = st.text_area(
        "Ticket text",
        height=260,
        placeholder=(
            "Paste the full ticket here — subject, body, and any useful ticket metadata "
            "(player's platform, account info they provided, attachments mentioned, etc.). "
            "You can also leave this empty and attach screenshots only."
        ),
        key="ticket_input",
    )
    guidance = st.text_area(
        "Agent guidance (optional)",
        height=90,
        placeholder=(
            "e.g. \"ask the player for their Player ID and platform first\" or "
            "\"focus on the disconnect penalty, ignore the cosmetic complaint\"."
        ),
        help=(
            "Free-form note that shapes all three outputs. Treated as a "
            "directive from you, but the agent will still follow hard rules "
            "(PII redaction, escalation, no invented procedures) even if your "
            "guidance contradicts them."
        ),
        key="ticket_guidance",
    )

with side_col:
    st.markdown("**Screenshots (optional)**")
    uploaded_images = st.file_uploader(
        "Upload images",
        type=["png", "jpg", "jpeg", "webp", "gif"],
        accept_multiple_files=True,
        label_visibility="collapsed",
        key=f"ticket_images_{st.session_state['uploader_nonce']}",
    )

    paste_result = paste_image_button(
        label="📋 Paste image from clipboard",
        key="ticket_paste_button",
        errors="ignore",
    )
    if paste_result.image_data is not None:
        buf = io.BytesIO()
        paste_result.image_data.save(buf, format="PNG")
        png = buf.getvalue()
        # The component re-returns the last paste on every rerun; dedupe on content.
        digest = hashlib.sha1(png).hexdigest()
        if st.session_state.get("ticket_last_paste_hash") != digest:
            st.session_state["ticket_last_paste_hash"] = digest
            st.session_state["pasted_images"].append(png)

    st.caption(
        "Clipboard paste works in Chrome, Edge, and Safari (Firefox blocks it). "
        "Each image is transcribed verbatim and added to the ticket evidence."
    )

    pasted = st.session_state["pasted_images"]
    if pasted:
        thumb_cols = st.columns(3)
        for i, png in enumerate(pasted):
            with thumb_cols[i % 3]:
                st.image(png, caption=f"Pasted #{i + 1}", width="stretch")
                st.button(
                    "Remove",
                    key=f"remove_paste_{i}",
                    on_click=_remove_pasted,
                    args=(i,),
                    width="stretch",
                )

image_count = len(uploaded_images or []) + len(st.session_state["pasted_images"])
has_input = bool(ticket.strip()) or image_count > 0

btn_a, btn_b, btn_info = st.columns([1, 1, 4], vertical_alignment="center")
run_clicked = btn_a.button(
    "Draft response",
    type="primary",
    width="stretch",
    disabled=not has_input or bool(missing_keys),
)
btn_b.button("Clear all", on_click=_reset_inputs, width="stretch")
if missing_keys:
    btn_info.caption(f"Set {', '.join(missing_keys)} in `.env` to enable drafting.")
elif image_count:
    btn_info.caption(f"{image_count} screenshot(s) attached.")

if run_clicked:
    image_bytes: list[bytes] = [f.getvalue() for f in (uploaded_images or [])]
    image_bytes.extend(st.session_state["pasted_images"])
    with st.status("Running multi-agent pipeline...", expanded=False) as status:
        started = time.perf_counter()
        try:
            run = run_agent(
                ticket,
                images=image_bytes or None,
                guidance=guidance,
                on_stage=lambda label: status.update(label=label),
            )
            elapsed = time.perf_counter() - started
            st.session_state["last_run"] = run
            st.session_state["last_wall_time"] = elapsed
            status.update(label=f"Done in {elapsed:.1f}s", state="complete")
        except Exception as exc:
            status.update(label="Pipeline failed", state="error", expanded=True)
            msg = str(exc)
            if "rate_limit_exceeded" in msg or "Request too large" in msg or "tokens per min" in msg:
                st.error(
                    "OpenAI rate limit hit (TPM ceiling). Either:\n\n"
                    "- Lower `RETRIEVE_FINAL_K` and/or `ROLE_BOOST_ARTICLES` in `.env`.\n"
                    "- Or upgrade your OpenAI tier for a higher TPM limit."
                )
            else:
                st.error(f"Pipeline failed: {exc}")
            with st.expander("Traceback"):
                st.code(traceback.format_exc())


# --- Result rendering ------------------------------------------------------

run = st.session_state.get("last_run")
if run is not None:
    out: AgentOutput = run.output
    cls: ClassifierOutput = run.classification
    pr = run.pipeline_run

    st.divider()

    # --- Alerts ---
    if out.escalation_flag:
        target = run.safety.escalation_target if run.safety else ""
        st.error(
            f"**⚠ Escalation flagged:** {out.escalation_reason}"
            + (f"  \n**Target:** {target}" if target else "")
        )
    if run.safety and run.safety.must_redact:
        pii_types = ", ".join(sorted({p.pii_type for p in run.safety.pii_detected if p.must_redact}))
        st.warning(f"**🔒 PII detected — redact before sending:** {pii_types}")

    # --- Summary row ---
    final_qa = run.qa_results[-1] if run.qa_results else None
    s1, s2, s3, s4, s5 = st.columns(5)
    if final_qa:
        s1.metric(
            "QA score",
            f"{final_qa.overall_score:.0%}",
            delta="Pass" if final_qa.passed else "Fail",
            delta_color="normal" if final_qa.passed else "inverse",
        )
        critical_fails = sum(1 for c in final_qa.checks if not c.passed and c.severity == "critical")
        s2.metric("Critical fails", critical_fails)
    else:
        s1.metric("QA score", "—")
        s2.metric("Critical fails", "—")
    s3.metric("QA retries", run.retry_count)
    s4.metric("Confidence", out.confidence.title())
    wall = st.session_state.get("last_wall_time")
    s5.metric("Wall time", f"{wall:.1f}s" if wall is not None else "—")

    if final_qa and not final_qa.passed and final_qa.qa_agent_notes:
        st.info(f"**QA notes:** {final_qa.qa_agent_notes}")

    if out.missing_info:
        with st.container(border=True):
            st.markdown("**Missing information to ask the player**")
            st.markdown("\n".join(f"- {q}" for q in out.missing_info))

    # --- Output tabs ---
    tab_reply, tab_note, tab_steps = st.tabs(["✉️ Player reply", "📝 Internal note", "🔎 Next steps"])

    with tab_reply:
        if pr:
            lang = run.safety.detected_language if run.safety else "?"
            st.caption(
                f"Confidence: **{CONFIDENCE_BADGE.get(pr.reply_output.reply_confidence, '?')}** · "
                f"Language: **{lang}**"
            )
        st.code(out.player_reply.strip(), language="markdown", wrap_lines=True)

    with tab_note:
        if pr:
            st.caption(f"Confidence: **{CONFIDENCE_BADGE.get(pr.note_output.note_confidence, '?')}**")
        st.code(out.internal_note.strip(), language="markdown", wrap_lines=True)

    with tab_steps:
        if pr:
            st.caption(f"Confidence: **{CONFIDENCE_BADGE.get(pr.steps_output.steps_confidence, '?')}**")
        steps_md = "\n".join(f"{i}. {step}" for i, step in enumerate(out.next_steps, start=1))
        st.code(steps_md or "(no steps)", language="markdown", wrap_lines=True)

    if out.notes_for_agent:
        st.info(f"**Notes from agent:** {out.notes_for_agent}")

    # --- Citations ---
    with st.expander(f"Cited sources ({len(out.citations)})", expanded=True):
        if not out.citations:
            st.markdown("_No sources cited. Treat this draft as low-confidence._")
        lines = []
        for cit in out.citations:
            title = f"[{cit.article}]({cit.source_url})" if cit.source_url else f"**{cit.article}**"
            lines.append(f"- {title} — {cit.section}")
        if lines:
            st.markdown("\n".join(lines))

    # --- QA detail ---
    if run.qa_results:
        with st.expander("QA detail", expanded=False):
            for i, qa in enumerate(run.qa_results, start=1):
                st.markdown(
                    f"**QA pass {i}** — score {qa.overall_score:.0%} · "
                    f"{'✅ Pass' if qa.passed else '❌ Fail'}"
                )
                failed = [c for c in qa.checks if not c.passed]
                passed_n = len(qa.checks) - len(failed)
                lines = [
                    f"- {SEVERITY_ICON.get(c.severity, '•')} `{c.rule_id}` ({c.severity})"
                    + (f" — {c.detail}" if c.detail else "")
                    for c in failed
                ]
                lines.append(f"- ✅ {passed_n} of {len(qa.checks)} checks passed")
                st.markdown("\n".join(lines))
                if not qa.passed:
                    for label, text in (
                        ("Note", qa.note_revision),
                        ("Reply", qa.reply_revision),
                        ("Steps", qa.steps_revision),
                    ):
                        if text:
                            st.markdown(f"**{label} revision feedback:** {text}")
                if i < len(run.qa_results):
                    st.divider()

    # --- Timings ---
    with st.expander("Pipeline timings", expanded=False):
        t = run.timings
        rows = [
            ("Vision", t.vision),
            ("Classifier", t.classifier),
            ("Retrieval (concurrent with safety)", t.retrieval),
            ("Safety (concurrent with retrieval)", t.safety),
            ("Drafting (parallel)", t.drafting),
        ] + [(f"QA pass {i}", q) for i, q in enumerate(t.qa, start=1)]
        st.markdown("\n".join(f"- **{label}:** {secs:.2f}s" for label, secs in rows))

    if run.screenshot_text:
        with st.expander("Screenshot transcription", expanded=False):
            st.caption(
                "Verbatim text the vision model extracted from your attached "
                "screenshot(s). All drafting agents saw exactly this."
            )
            st.code(run.screenshot_text, language="markdown", wrap_lines=True)

    if run.guidance:
        with st.expander("Agent guidance applied", expanded=False):
            st.code(run.guidance, language="markdown", wrap_lines=True)

    # --- Debug ---
    with st.expander(f"Retrieved chunks ({len(run.hits)})", expanded=False):
        st.markdown(
            "\n".join(
                f"- `[{(h.metadata or {}).get('type', '?')}]` **{h.title}** › {h.heading}  \n"
                f"  score={h.score:.3f} · source={h.source} · id={(h.metadata or {}).get('article_id', '?')}"
                for h in run.hits
            )
            or "_No chunks retrieved._"
        )

    with st.expander("Debug: raw agent outputs", expanded=False):
        debug_tabs = st.tabs(["Classifier", "Safety", "Note agent", "Reply agent", "Steps agent", "Assembled"])
        with debug_tabs[0]:
            st.json(cls.model_dump())
        with debug_tabs[1]:
            st.json(run.safety.model_dump() if run.safety else {})
        with debug_tabs[2]:
            st.json(pr.note_output.model_dump() if pr else {})
        with debug_tabs[3]:
            st.json(pr.reply_output.model_dump() if pr else {})
        with debug_tabs[4]:
            st.json(pr.steps_output.model_dump() if pr else {})
        with debug_tabs[5]:
            st.json(out.model_dump())
