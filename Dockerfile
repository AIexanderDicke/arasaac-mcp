# syntax=docker/dockerfile:1
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    ARASAAC_ICONS_DIR=/app/icons \
    ARASAAC_OUTPUT_DIR=/app/output \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Unprivileged user first, so COPY can use --chown.
RUN useradd --create-home --uid 10001 app

# Dependencies only.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra mcp --no-install-project --no-dev

# Project code, fonts, recipe and generated skill.
COPY --chown=app:app src/ ./src/
COPY --chown=app:app assets/ ./assets/
COPY --chown=app:app skills/ ./skills/
COPY --chown=app:app scripts/prompt.md ./scripts/prompt.md
RUN uv sync --frozen --extra mcp --no-dev

# Pictograms last: 338 MB and rarely change.
COPY --chown=app:app icons/ ./icons/

# Debug renders served under /sheet/<name>.
RUN mkdir -p /app/output && chown app:app /app/output

USER app

EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/arasaac-mcp"]
