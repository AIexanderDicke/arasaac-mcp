# syntax=docker/dockerfile:1
#
# ARASAAC pictogram MCP server.
#
# The image is self-contained and offline: it bundles the code, the fonts and
# the ~338 MB pictogram set.  It runs **no LLM** and needs no API key — the MCP
# host brings the model.  Serves streamable HTTP on :8000/mcp by default; pass
# `--transport stdio` for a local stdio host.
#
#   docker build -t arasaac-mcp .
#   docker run --rm -p 8000:8000 arasaac-mcp
#   docker run --rm -i arasaac-mcp --transport stdio
#
FROM ghcr.io/astral-sh/uv:python3.13-bookworm-slim

ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never \
    ARASAAC_ICONS_DIR=/app/icons \
    PYTHONUNBUFFERED=1

WORKDIR /app

# 1) Dependencies only — cached across code changes.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --extra mcp --no-install-project --no-dev

# 2) Project code, fonts, recipe and generated skill.
COPY src/ ./src/
COPY assets/ ./assets/
COPY skills/ ./skills/
COPY prompt.md ./
RUN uv sync --frozen --extra mcp --no-dev

# 3) Pictograms last: 338 MB and rarely change, so they stay in their own layer.
COPY icons/ ./icons/

# Run unprivileged.
RUN useradd --create-home --uid 10001 app && chown -R app:app /app
USER app

EXPOSE 8000
ENTRYPOINT ["/app/.venv/bin/arasaac-mcp"]
CMD ["--transport", "http", "--host", "0.0.0.0", "--port", "8000"]
