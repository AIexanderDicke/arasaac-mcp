# syntax=docker/dockerfile:1
# Small app image: code + fonts + only the ~9 MB pictogram word index
# (icons/metadata_de.json). The ~338 MB PNG set is *not* baked in — a pictogram
# is fetched from ARASAAC on first use into ARASAAC_CACHE_DIR (mount a volume
# there). For an offline/air-gapped run, set ARASAAC_FETCH=off and pre-populate
# that cache (or icons/) with the PNGs from scripts/download_icons.py.
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    ARASAAC_ICONS_DIR=/app/icons \
    ARASAAC_CACHE_DIR=/app/cache \
    ARASAAC_OUTPUT_DIR=/app/output \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Unprivileged user first, so COPY can use --chown.
RUN useradd --create-home --uid 10001 app

# Dependencies only.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project --no-dev

# Project code, fonts, recipe and generated skill.
COPY --chown=app:app arasaac_mcp/ ./arasaac_mcp/
COPY --chown=app:app assets/ ./assets/
COPY --chown=app:app skills/ ./skills/
COPY --chown=app:app scripts/prompt.md ./scripts/prompt.md
RUN uv sync --frozen --no-dev

# Word index only (~9 MB). The PNG set is fetched on demand into the cache.
COPY --chown=app:app icons/metadata_de.json ./icons/metadata_de.json

# Fetched pictograms (cache) and debug renders served under /sheet/<name>.
RUN mkdir -p /app/output /app/cache && chown app:app /app/output /app/cache

USER app

EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/arasaac-mcp"]
