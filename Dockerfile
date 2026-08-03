FROM python:3.11-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    MIRA_DB_PATH=/data/sqlite/mira.db \
    CHROMA_DB_PATH=/data/chroma \
    LOCAL_EMBEDDING_CACHE_DIR=/data/model-cache

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt ./
RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt

COPY . .

RUN mkdir -p /data/sqlite /data/chroma /data/model-cache

EXPOSE 8000

CMD ["uvicorn", "api.main:app", "--host", "0.0.0.0", "--port", "8000"]

FROM base AS dev

COPY requirements-dev.txt ./
RUN python -m pip install -r requirements-dev.txt

FROM base AS paritok

# MIRA uses hosted compression and passthrough tool discovery. The upstream
# `proxy` extra also installs sentence-transformers and a CUDA PyTorch build,
# which are unnecessary for this configuration; FastAPI already supplies the
# proxy's Starlette/Uvicorn runtime dependencies.
RUN python -m pip install "paritok==1.2.7"

# Paritok 1.2.7 computes OpenAI history compression but discards the returned
# message list. Keep this pinned compatibility patch explicit and fail the build
# when the upstream source changes, so it can be removed after an upstream fix.
RUN PARITOK_SERVER="/usr/local/lib/python3.11/site-packages/paritok/proxy/server.py" \
    && grep -q '_, processed_tools, stats, stubbed = engine.process_request' "$PARITOK_SERVER" \
    && sed -i \
      's/        _, processed_tools, stats, stubbed = engine.process_request/        parsed.messages, processed_tools, stats, stubbed = engine.process_request/' \
      "$PARITOK_SERVER" \
    && grep -q 'parsed.messages, processed_tools, stats, stubbed = engine.process_request' \
      "$PARITOK_SERVER"

# The same release tracks the number of compressed history turns but omits their
# token counts from /stats. Provider usage remains MIRA's authoritative measure;
# this makes Paritok's local operational counter useful as a secondary signal.
RUN PARITOK_WRAPPER="/usr/local/lib/python3.11/site-packages/paritok/middleware/wrapper.py" \
    && grep -q 'stats.history_turns_compressed = len(old_messages)' "$PARITOK_WRAPPER" \
    && sed -i \
      '/    stats.history_turns_compressed = len(old_messages)/a\    stats.original_tokens += count_tokens(old_text, upstream_model); stats.compressed_tokens += count_tokens(summary, upstream_model); stats.items_compressed += 1' \
      "$PARITOK_WRAPPER" \
    && grep -q 'stats.original_tokens += count_tokens(old_text, upstream_model)' \
      "$PARITOK_WRAPPER"

# Expose per-request compression measurements to MIRA. Paritok 1.2.7 only
# publishes process-wide totals at /stats, which cannot be attributed safely in
# a multi-user service. These headers cover the exact request handled here.
RUN PARITOK_SERVER="/usr/local/lib/python3.11/site-packages/paritok/proxy/server.py" \
    && grep -q 'return JSONResponse(content=final_body, status_code=status_code, headers=resp_headers)' \
      "$PARITOK_SERVER" \
    && python /app/scripts/patch_paritok_response_headers.py "$PARITOK_SERVER" \
    && grep -q 'x-paritok-tokens-saved' "$PARITOK_SERVER"
