# Everdawn Support: an AI-first player support platform

Players open tickets in a help center and get a cited answer from a multi-agent RAG pipeline in under a minute. Tickets then follow a real lifecycle: waiting on the player, handed to a human, on hold, solved. A staff console shows the queue, every ticket's history and the AI's reasoning, plus reporting on how well the AI and the team are doing.

> **Everdawn** (a game) and **NovaStar Games** (its studio) are fictional. The `kb/` folder holds invented demo content so the platform runs out of the box. Real deployments use private knowledge bases that are not in this repository.

---

## Why this project exists

It started as an agent-assist copilot. The original problem: one 22K-token prompt holding tone rules, escalation policy, PII handling, note templates and SOPs. Models systematically ignored rules in the middle of the context ("lost in the middle"), so quality dropped on complex tickets and internal macro names leaked into replies.

The fix was a pipeline of focused agents, each seeing only the context it needs. With QA and safety in place, the next question was whether the AI could answer players directly. This platform answers that, with guardrails:

- **The AI replies first, every time,** and says it's an AI (EU AI Act Art. 50 transparency).
- **A deterministic routing policy** (`server/services/routing.py`, unit-tested) decides what happens next. The model never decides alone.
- **Safety flags** (legal threats, threats of violence, self-harm) get a calm holding reply and go to the top of the human queue. Self-harm signals also show crisis resources to the player right away.
- **Players are always one click from a person** ("I still need help"). Once a human replies, the AI stays out of that ticket.
- **Internal SOPs never reach players.** Only articles marked `audience: public` can be suggested or cited to them.

---

## What's in it

### Player Help Center (`/`)
- **One composer.** Matching help articles appear *as you type* (BM25 with prefix matching: no LLM, no API cost per keystroke). Many questions end there; that's tracked as deflection.
- **Inline passwordless sign-in.** In demo mode the magic link is verified instantly, with no email server.
- **Live progress.** After submitting, the player watches the AI work through its stages over Server-Sent Events, then gets an answer with source chips that open the article in a side sheet.
- **"Waiting on you" checklists.** When the AI or an agent needs something (an ID, a log file, a platform), the player answers inline and the AI picks the ticket back up automatically.
- **"That fixed it" / "I still need help",** CSAT after resolution, a "My tickets" history, drag/paste screenshots, light and dark themes, mobile-first.

### Support Console (`/console`)
- **Queue views with live counts:** Needs attention, AI review (low-confidence answers), Assigned to me, Waiting on player, On hold, Solved. Search, priority filter, `j`/`k` navigation, `⌘K` palette.
- **Ticket workspace:** pinned safety/PII/hand-off banners, the full conversation with internal notes, an activity timeline from the audit log, and a reply composer that can request checklist items and set the next status.
- **Copilot panel:** QA score and failed checks, the routing decision, classification, safety findings, suggested next steps, the AI's internal note, sources (including internal SOPs), per-stage timing, and on-demand reply drafts with guidance, signed by the requesting agent.

### Reporting (`/console/reports`)
AI resolution rate with period-over-period change, first response and resolution times, CSAT, daily volume by outcome, hand-off reasons, topics, **knowledge gaps** (topics where the AI lacked a good article: write these next), pending-ticket aging, QA pass rate, stage latency, most-cited articles and self-service deflection.

---

## Architecture

```
 web/  React + Vite + TypeScript ──HTTP + SSE──▶  server/  FastAPI + SQLModel
   Help Center · Console · Reports                  │
                                                    ├─ tickets, messages, checklists, audit events (SQLite / Postgres)
                                                    ├─ job runner: AI runs on worker threads, stages streamed live
                                                    ├─ routing policy: AI output → status, priority, hand-off
                                                    ├─ lifecycle: reminders (3d), auto-solve (7d), auto-close (4d)
                                                    └─ src/  multi-agent pipeline ────────────────┐
                                                                                                  ▼
   Ticket ─▶ Vision ─▶ Classifier ─┬─▶ Hybrid retrieval (Chroma + BM25, RRF) ─┐
                                   └─▶ Safety agent (PII, escalation) ────────┴─▶ Note ∥ Reply ∥ Steps ─▶ QA ⟲ targeted retries
```

- **Retrieval and safety run concurrently.** They only depend on the classifier.
- **One pipeline, two personas.** The reply and QA agents take `persona="ai_assistant"` for player-facing answers and `"human_agent"` for console drafts.
- **Mock pipeline mode** (`PIPELINE_MODE=mock`, the default) walks the same stages with realistic, KB-grounded answers and makes **no API calls**. Demos, frontend work and the test suite all run free; set `PIPELINE_MODE=live` to use real models.
- **Provider-agnostic models:** OpenAI, Anthropic, Ollama or any OpenAI-compatible endpoint, configured per agent in `.env`.

---

## Quickstart

### Docker (one command)

```bash
docker compose up --build
```

Open http://localhost:8000 for the help center and http://localhost:8000/console for the console. It starts in mock mode with 300 seeded demo tickets, no API key needed.

For real models, copy `.env.example` to `.env`, add your key, and start with `PIPELINE_MODE=live`. The knowledge base is embedded on first start. For Postgres instead of SQLite, see the comment in `docker-compose.yml` and run `docker compose --profile postgres up`.

### Local development

Requires Python 3.11+ and Node 20+.

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python -m server.seed                      # optional: demo tickets for the console and reports
uvicorn server.main:app --reload --port 8000
```

In a second terminal:

```bash
cd web && npm install && npm run dev       # http://localhost:5173 (proxies /api to :8000)
```

Console sign-in: `agent@everdawn.dev`, `lead@everdawn.dev` or `admin@everdawn.dev` with the password in `STAFF_DEMO_PASSWORD` (default `everdawn-demo`). Change it for anything beyond a local demo.

For live mode, embed the knowledge base once with `python -m src.ingest`.

### Useful commands

| Command | What it does |
|---|---|
| `pytest` | 34 backend tests (routing policy, lifecycle, API flows, persona wiring, reports, seeding), all offline |
| `python -m server.seed --reset` | Remove demo data (real tickets are untouched) |
| `cd web && npm run gen:api` | Regenerate TypeScript API types from the FastAPI OpenAPI schema |
| `cd web && npm run build` | Production build; FastAPI serves `web/dist` automatically |
| `python cli.py --ticket "…"` | Run the pipeline on one ticket from the terminal |

---

## Project structure

```
server/                  FastAPI platform
├── main.py              app, lifespan, serves the built SPA
├── models.py            tickets, messages, checklists, AI runs, audit events
├── routers/             auth · help (player) · console (staff) · reports
├── services/
│   ├── routing.py       the policy: AI result → status / priority / hand-off
│   ├── jobs.py          AI runs on worker threads + live stages
│   ├── pipeline.py      bridge to src/ (live) or the mock pipeline
│   ├── tickets.py       status transitions, audit trail, serialization
│   ├── lifecycle.py     reminders, auto-solve, auto-close
│   └── reports.py       KPIs and breakdowns
├── kb.py                help-center catalog and instant suggestions
└── seed.py              realistic demo histories (no LLM calls)
src/                     multi-agent RAG pipeline (classifier, retrieval, safety, note, reply, steps, QA)
web/src/
├── help/                player help center
├── console/             staff console and reporting
└── components/ui/       design-system primitives (Radix + Tailwind)
kb/demo/                 internal SOPs (fictional)
kb/help/                 public help articles (fictional)
prompts/                 per-agent prompts, incl. the AI-assistant persona
tests/                   pytest suite
```

---

## Prototype limits

The scale-out paths below are known; they're out of scope for a demo.

- **Single process.** AI runs use a thread pool and live updates use in-process pub/sub. Production would use a queue (arq/RQ on Redis) and Redis pub/sub for SSE.
- **No mail server.** Magic links are shown in the UI (`DEV_MAGIC_LINKS=true`), which means anyone can sign in as any player email. Turn it off and wire an email provider before real use.
- **Reports are computed per request.** At volume, use daily rollups or a warehouse.
- **Mock mode is not the AI.** Its answers come from keyword rules plus article text. Judge answer quality in live mode.

The original Streamlit agent-assist UI is preserved on the `legacy/streamlit-copilot` branch.
