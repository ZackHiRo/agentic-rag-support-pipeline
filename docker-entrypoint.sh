#!/bin/bash
# docker-entrypoint.sh
# Runs before the Streamlit app starts.
# Handles the KB build pipeline on first run (or when forced).
set -euo pipefail

echo ""
echo "═══════════════════════════════════════════════════"
echo "  Everdawn Support Agent"
echo "═══════════════════════════════════════════════════"

# ── Sanity checks ─────────────────────────────────────────────────────────────

if [ -z "${OPENAI_API_KEY:-}" ] && [ "${LLM_PROVIDER:-openai}" = "openai" ]; then
    echo "ERROR: OPENAI_API_KEY is not set."
    echo "  Pass it via --env-file .env or -e OPENAI_API_KEY=sk-..."
    exit 1
fi

if [ "${LLM_PROVIDER:-openai}" = "anthropic" ] && [ -z "${ANTHROPIC_API_KEY:-}" ]; then
    echo "ERROR: ANTHROPIC_API_KEY is not set and LLM_PROVIDER=anthropic."
    exit 1
fi

# ── Step 1: HTML → Markdown (optional) ────────────────────────────────────────
HTML_COUNT=0
if [ -d /app/game ] || [ -d /app/general ]; then
    HTML_COUNT=$((find /app/game /app/general -name "*.html" 2>/dev/null || true) | wc -l | tr -d ' ')
fi
KB_COUNT=$((find /app/kb -name "*.md" 2>/dev/null || true) | wc -l | tr -d ' ')

if [ "$HTML_COUNT" -gt 0 ]; then
    if [ "$KB_COUNT" -eq 0 ] || [ "${REBUILD_KB:-false}" = "true" ]; then
        echo ""
        echo "► Step 1/3: Converting $HTML_COUNT HTML file(s) to Markdown..."
        python -m src.html_to_md
    else
        echo "► Step 1/3: KB already has $KB_COUNT articles — skipping HTML conversion."
        echo "  (Set REBUILD_KB=true to force a rebuild)"
    fi
fi

# ── Step 2: Build prompt bundles (optional) ───────────────────────────────────
python -m src.build_prompts

# ── Step 3: Embed KB into Chroma ─────────────────────────────────────────────
CHUNK_COUNT=$(python3 -c "
import os, chromadb
from chromadb.config import Settings
try:
    c = chromadb.PersistentClient(path='/app/.chroma', settings=Settings(anonymized_telemetry=False))
    print(c.get_or_create_collection('support_kb').count())
except Exception:
    print(0)
" 2>/dev/null || echo "0")

if [ "$CHUNK_COUNT" -eq 0 ] || [ "${REBUILD_KB:-false}" = "true" ]; then
    echo ""
    echo "► Step 3/3: Embedding KB into Chroma (this may take a minute on first run)..."
    python -m src.ingest
else
    echo "► Step 3/3: Chroma already has $CHUNK_COUNT chunks — skipping ingest."
    echo "  (Set REBUILD_KB=true to force a re-embed)"
fi

# ── Launch Streamlit ─────────────────────────────────────────────────────────
echo ""
echo "═══════════════════════════════════════════════════"
echo "  Starting Streamlit on http://0.0.0.0:8501"
echo "═══════════════════════════════════════════════════"
echo ""

exec streamlit run app.py \
    --server.port="${STREAMLIT_SERVER_PORT:-8501}" \
    --server.address="${STREAMLIT_SERVER_ADDRESS:-0.0.0.0}" \
    --server.headless=true \
    --browser.gatherUsageStats=false
