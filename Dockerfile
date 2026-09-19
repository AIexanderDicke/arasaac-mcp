# syntax=docker/dockerfile:1
# App image: code + fonts on top of the published icon base image (which already
# carries the pictograms). Layers are shared, so code-only rebuilds do not
# re-copy the ~338 MB icon set. To build without GHCR, build the base locally
# from a checkout that has icons/ and point ICONS_IMAGE at it:
#   docker build -f Dockerfile.icons -t arasaac-icons:de-500 .
#   docker build --build-arg ICONS_IMAGE=arasaac-icons:de-500 -t arasaac-mcp .
ARG ICONS_IMAGE=ghcr.io/aiexanderdicke/arasaac-icons:de-500
FROM ${ICONS_IMAGE}

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    ARASAAC_ICONS_DIR=/app/icons \
    ARASAAC_OUTPUT_DIR=/app/output \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Unprivileged user first, so COPY can use --chown. uid matches Dockerfile.icons.
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

# Debug renders served under /sheet/<name>.
RUN mkdir -p /app/output && chown app:app /app/output

USER app

EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/arasaac-mcp"]
