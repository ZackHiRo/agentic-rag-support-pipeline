# Multi-Agent RAG Support Agent

A production-grade multi-agent RAG system for video game customer support automation. Built to replace an overloaded single-prompt LLM approach that suffered from context degradation, hallucinations, and rule adherence failures.

---

## About this project

**The problem:** Fitting tone rules, escalation policies, PII handling, internal note schemas, and operational SOPs into a single 22K-token prompt caused models to systematically ignore rules located in the middle of the context window (the "lost-in-the-middle" problem). Quality degraded on complex tickets, and hallucinations occasionally leaked internal macro codes or failed critical escalation criteria.

**The solution:** A 6-agent pipeline where each agent sees only the context and prompt it needs:
- **Vision Agent:** Transcribes ticket screenshots and crash logs directly into context.
- **Classifier Agent:** Derives topic categories, urgency, and targeted multi-angle search queries.
- **Hybrid Retrieval:** Fuses Chroma vector search (dense embeddings) and BM25 (lexical exact-match) using Reciprocal Rank Fusion (RRF).
- **Safety Agent:** Zero-SOP safety classification for PII detection (must-redact vs. non-redactable) and escalation triggers (legal, Real Life Threats, sensitive inquiries).
- **Parallel Drafting Agents (ThreadPoolExecutor):**
  - *Internal Note Agent:* Formats helpdesk internal documentation with `(pending)` markers for human review.
  - *Player Reply Agent:* Drafts public, language-matched replies adhering strictly to studio tone rules.
  - *Next Steps Agent:* Extracts ordered investigation steps in back-office tools.
- **QA Agent:** Evaluates all drafting outputs against a 19-check normative rubric and drives targeted retries if critical checks fail.

**Design scope: an agent-assist copilot, not an autopilot.** The pipeline is intentionally not connected to a helpdesk platform. It drafts the player reply, the internal note and the next steps for a human support agent, who reviews, edits and sends. Keeping a person in the loop is a deliberate choice for player-facing support, where escalations, personal data and compensation decisions need human judgement. Because the output is structured (Pydantic), wiring it into a helpdesk API later is a thin integration layer, not a redesign.

> **Note:** Knowledge bases used in real deployments are private and not included in this repository. The `kb/demo/` folder contains fictional sample articles (the "Everdawn" game by "NovaStar Games" is invented) that demonstrate the system structure and let reviewers run the agent locally out of the box.

---

## Architecture Overview

```
                         Incoming Ticket (+ Screenshots)
                                       │
                                       ▼
                         ┌───────────────────────────┐
                         │   Stage 1: Vision Model   │ (Transcribe screenshots)
                         └─────────────┬─────────────┘
                                       │
                         ┌─────────────▼─────────────┐
                         │ Stage 2: Classifier Agent │ (Topics, urgency, search queries)
                         └──────┬─────────────┬──────┘
                                │             │
            ┌───────────────────┘             └───────────────────┐
            ▼                                                     ▼
┌────────────────────────┐                             ┌───────────────────────┐
│ Stage 3: Hybrid Search │                             │ Stage 4: Safety Agent │
│   (Chroma + BM25 RRF)  │                             │ (PII & Escalation)    │
└───────────┬────────────┘                             └───────────┬───────────┘
            │                                                     │
            └─────────────────────────┬───────────────────────────┘
                                      │
                     ┌────────────────┴────────────────┐
                     ▼                                 ▼
        ┌─────────────────────────────────────────────────────────────┐
        │        Stage 5: Parallel Drafting (ThreadPoolExecutor)       │
        │  ┌──────────────────┐  ┌───────────────┐  ┌──────────────┐  │
        │  │Internal Note Agt │  │Player Reply Ag│  │Next Steps Ag │  │
        │  └────────┬─────────┘  └───────┬───────┘  └──────┬───────┘  │
        └───────────┼────────────────────┼─────────────────┼──────────┘
                    └────────────────────┼─────────────────┘
                                         ▼
                         ┌───────────────────────────┐
                         │    Stage 6: QA Agent      │◄── (Targeted Retry Loop)
                         │ (19-check rule validator) │
                         └─────────────┬─────────────┘
                                       │
                                       ▼
                       Final Structured Response (UI/CLI)
```

---

## Key Technical Features

- **Multi-Agent Orchestration:** Decomposes complex SOP compliance into focused single-responsibility agents, reducing prompt tokens by ~8K per call.
- **Hybrid Retrieval (RRF):** Dense vector embeddings (`text-embedding-3-small`) combined with sparse BM25 lexical search ensures high recall for both conceptual queries and exact game error codes / proper nouns.
- **LLM Provider Abstraction:** Provider-agnostic adapter layer supporting OpenAI, Anthropic, Ollama (local/free), and OpenAI-compatible endpoints with simple `.env` switching.
- **Rigorous Data Validation:** Structured outputs via Pydantic v2 schemas across all pipeline stages.
- **Automated QA & Targeted Retry:** A dedicated QA agent scores responses (0.0–1.0) and triggers targeted re-generation only for failing components.
- **Streamlit Production UI:** Real-time metrics, per-stage timing breakdowns, source citations, and clipboard shortcuts.
- **Containerization:** Docker & Docker Compose setup ready for deployment.

---

## Quickstart

### 1. Installation

Requires Python 3.11+.

```bash
# Clone the repository
git clone https://github.com/your-username/support-agent.git
cd support-agent

# Create virtual environment
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Configuration

Copy `.env.example` to `.env` and supply your OpenAI or Anthropic API key:

```bash
cp .env.example .env
```

```ini
OPENAI_API_KEY=sk-...
LLM_PROVIDER=openai
OPENAI_MODEL=gpt-4.1
OPENAI_CLASSIFIER_MODEL=gpt-4.1-mini
```

*(To run completely free locally, set `LLM_PROVIDER=ollama` and `LLM_BASE_URL=http://localhost:11434/v1`)*

### 3. Ingest Demo Knowledge Base

Embed the fictional demo articles in `kb/demo/` into the local Chroma vector index:

```bash
python -m src.ingest
```

### 4. Run the Application

#### Streamlit UI (Recommended)

```bash
streamlit run app.py
```

Open `http://localhost:8501` in your browser. Paste a sample ticket or describe an issue (e.g. *"I keep getting disconnected from the game and received a matchmaking penalty, help!"*), then click **Draft response**.

#### Terminal CLI

```bash
# Test inline
python cli.py --ticket "My game disconnects during matchmaking and gives Error 105" --show-sources

# Test with JSON dump
python cli.py --ticket "Account verification assistance required for EVD-1029-3841" --json
```

---

## Project Structure

```
support-agent/
├── app.py                      # Streamlit UI: live stage progress, output tabs, QA + timing panels
├── cli.py                      # Command-line interface
├── requirements.txt            # Python dependencies
├── Dockerfile                  # Container build definition
├── docker-compose.yml          # Container service definition
├── docker-entrypoint.sh        # Container startup orchestration
│
├── kb/                         # Knowledge base directory
│   └── demo/                   # Fictional demonstration SOPs & handbooks
│       ├── connection-issues.md
│       ├── account-recovery.md
│       ├── matchmaking-error-105.md
│       └── tone-and-formatting.md
│
├── prompts/                    # Specialized agent prompt templates
│   ├── safety.md               # Safety Agent: PII and escalation rules
│   ├── internal_note.md        # Note Agent: ticket documentation template
│   ├── note_format.md          # Internal note format specification
│   ├── player_reply.md         # Reply Agent: customer communication instructions
│   ├── tone_rules.md           # Brand voice and prohibited language rules
│   ├── next_steps.md           # Steps Agent: back-office investigation procedures
│   ├── qa.md                   # QA Agent: 19-check validation rubric
│   └── process_rules.example.md# Pre-refactor example reference
│
└── src/                        # Core application code
    ├── agent.py                # Main entrypoint and classifier pass
    ├── config.py               # Provider configuration and model routing
    ├── llm.py                  # Provider-agnostic LLM adapter (OpenAI, Anthropic, Ollama)
    ├── ingest.py               # Markdown chunker and vector embedding pipeline
    ├── retrieve.py             # Hybrid RAG retriever (Chroma + BM25 + RRF)
    ├── schemas.py              # Pydantic data schemas
    ├── vision.py               # Screenshot transcription helper
    └── agents/                 # Multi-agent implementations
        ├── orchestrator.py     # Parallel executor and QA retry loop
        ├── safety.py           # Safety Agent runner
        ├── note.py             # Internal Note Agent runner
        ├── reply.py            # Player Reply Agent runner
        ├── steps.py            # Next Steps Agent runner
        └── qa.py               # QA Validator Agent runner
```

---

## License

This project is licensed under the MIT License — see the [LICENSE](LICENSE) file for details.
