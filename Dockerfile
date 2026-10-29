# ── Stage 1: build the React app ──────────────────────────────────────────────
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY web/ ./
RUN npm run build

# ── Stage 2: Python API (also serves the built app) ──────────────────────────
FROM python:3.12-slim

# build-essential is needed by chromadb's native extensions on first install.
RUN apt-get update && apt-get install -y --no-install-recommends build-essential curl \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash agent
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir --upgrade pip && pip install --no-cache-dir -r requirements.txt

COPY cli.py ./
COPY src/ ./src/
COPY server/ ./server/
COPY prompts/ ./prompts/
COPY kb/ ./kb/
COPY --from=web /web/dist ./web/dist
COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
RUN chmod +x /usr/local/bin/docker-entrypoint.sh \
 && mkdir -p data .chroma \
 && chown -R agent:agent /app

USER agent
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD curl -fs http://localhost:8000/api/health || exit 1

ENTRYPOINT ["docker-entrypoint.sh"]
