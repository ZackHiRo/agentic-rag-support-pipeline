#!/bin/bash
# Prepares the knowledge base and demo data, then starts the platform.
set -euo pipefail

MODE="${PIPELINE_MODE:-mock}"
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Everdawn Support Platform  (pipeline: ${MODE})"
echo "═══════════════════════════════════════════════════"

if [ "$MODE" = "live" ]; then
    # Embeddings always use OpenAI; the drafting models may use another provider.
    if [ -z "${OPENAI_API_KEY:-}" ]; then
        echo "ERROR: PIPELINE_MODE=live needs OPENAI_API_KEY (embeddings use OpenAI)."
        exit 1
    fi
    if [ "${LLM_PROVIDER:-openai}" = "anthropic" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
        echo "ERROR: LLM_PROVIDER=anthropic needs ANTHROPIC_API_KEY."
        exit 1
    fi

    python -m src.build_prompts

    # Embed the KB into Chroma on first run (or when forced). Mock mode skips
    # this entirely: it searches the markdown directly and makes no API calls.
    CHUNKS=$(python - <<'PY' 2>/dev/null || echo 0
import chromadb
from chromadb.config import Settings
c = chromadb.PersistentClient(path="/app/.chroma", settings=Settings(anonymized_telemetry=False))
print(c.get_or_create_collection("support_kb").count())
PY
)
    if [ "$CHUNKS" -eq 0 ] || [ "${REBUILD_KB:-false}" = "true" ]; then
        echo "► Embedding the knowledge base into Chroma (first run)…"
        python -m src.ingest
    else
        echo "► Knowledge base already indexed (${CHUNKS} chunks)."
    fi
fi

if [ "${SEED_DEMO:-true}" = "true" ]; then
    echo "► Seeding demo tickets for the console and reports (SEED_DEMO=false to skip)…"
    python -m server.seed --if-empty --tickets "${SEED_TICKETS:-300}" --days "${SEED_DAYS:-60}"
fi

echo "► Help center: http://localhost:8000   Console: http://localhost:8000/console"
exec uvicorn server.main:app --host 0.0.0.0 --port 8000 --proxy-headers --timeout-graceful-shutdown 10
