FROM python:3.11-slim

# ── System deps ───────────────────────────────────────────────────────────────
# build-essential is needed by chromadb's native extensions on first install.
RUN apt-get update && apt-get install -y --no-install-recommends \
        build-essential \
        curl \
    && rm -rf /var/lib/apt/lists/*

# ── Non-root user ─────────────────────────────────────────────────────────────
RUN useradd --create-home --shell /bin/bash agent
WORKDIR /app

# ── Python dependencies ───────────────────────────────────────────────────────
# Copy requirements first so Docker layer-caches the pip install step.
COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip \
 && pip install --no-cache-dir -r requirements.txt

# ── Application code ──────────────────────────────────────────────────────────
# Everything except secrets (.env) and generated data (kb/, .chroma/)
# which are mounted as volumes at runtime.
COPY app.py cli.py ./
COPY src/ ./src/
COPY prompts/ ./prompts/
COPY kb/ ./kb/

# ── Startup script ────────────────────────────────────────────────────────────
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh

# ── Directory structure ───────────────────────────────────────────────────────
# kb/ contains markdown knowledge base (persisted via volume or rebuilt on start).
# .chroma/ is the vector index (persisted via volume).
RUN mkdir -p kb/demo .chroma \
 && chown -R agent:agent /app

USER agent

EXPOSE 8501

# Streamlit telemetry + server settings
ENV STREAMLIT_BROWSER_GATHER_USAGE_STATS=false \
    STREAMLIT_SERVER_PORT=8501 \
    STREAMLIT_SERVER_ADDRESS=0.0.0.0 \
    STREAMLIT_SERVER_HEADLESS=true \
    STREAMLIT_THEME_BASE=dark

HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=3 \
    CMD curl -f http://localhost:8501/_stcore/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
