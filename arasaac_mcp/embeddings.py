"""Embedding clients for the vector search layer.

Two interchangeable embedders produce the vectors that
:mod:`arasaac_mcp.vector` stores in and retrieves from Qdrant:

- :class:`OpenAIEmbedder` — any OpenAI-compatible ``/embeddings`` endpoint
  (OpenRouter by default; a configurable model, e.g. ``qwen/qwen3-embedding-8b``
  or, for cheap test runs, ``liquid/lfm-2.5-embedding-350m:free``). Stdlib
  ``urllib`` only, with retries and backoff for rate limits.
- :class:`LocalEmbedder` — a local ``sentence-transformers`` model, no network
  and no API key (optional dev dependency, loaded lazily).

Config defaults come from ``ARASAAC_EMBED_*`` environment variables (see
:func:`make_embedder`); every knob can also be passed explicitly, which is what
the scripts and tests do.
"""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any, Protocol

#: Cloudflare in front of some endpoints rejects Python's default User-Agent.
USER_AGENT = "arasaac-mcp/0.1 (+https://github.com/aiexanderdicke/arasaac)"

DEFAULT_OPENAI_BASE_URL = "https://openrouter.ai/api/v1"
DEFAULT_OPENAI_MODEL = "qwen/qwen3-embedding-8b"
DEFAULT_LOCAL_MODEL = "Qwen/Qwen3-Embedding-0.6B"

#: Instruction prefix for query embeddings (qwen3-embedding style instruct
#: models score queries better with a task description; documents stay plain).
DEFAULT_QUERY_INSTRUCTION = (
    "Instruct: Retrieve the ARASAAC pictogram that best matches the request.\nQuery: "
)


class EmbeddingError(RuntimeError):
    """An embedding request failed (no key, offline, 4xx/5xx, bad payload)."""


class Embedder(Protocol):
    """Anything that turns texts into vectors."""

    model_name: str

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> list[list[float]]:
        """Embed ``texts``; ``is_query`` selects the query variant when the
        model distinguishes query and document embeddings."""
        ...


def embed_api_key() -> str | None:
    """API key for the embeddings endpoint (``ARASAAC_EMBED_API_KEY`` or
    ``OPENROUTER_API_KEY``)."""
    return os.environ.get("ARASAAC_EMBED_API_KEY") or os.environ.get("OPENROUTER_API_KEY") or None


def embed_provider() -> str:
    """Embedding provider, ``openai`` (default) or ``local``."""
    return os.environ.get("ARASAAC_EMBED_PROVIDER", "openai").strip().lower()


def make_embedder(
    provider: str | None = None,
    *,
    model: str | None = None,
    base_url: str | None = None,
    api_key: str | None = None,
    device: str | None = None,
    batch_size: int | None = None,
    query_instruction: str | None = None,
    timeout: float = 60.0,
    retries: int | None = None,
    backoff: float | None = None,
    min_interval: float | None = None,
) -> Embedder:
    """Build the embedder configured by ``ARASAAC_EMBED_*`` plus overrides.

    ``openai`` → :class:`OpenAIEmbedder` (default; OpenRouter base URL,
    ``qwen/qwen3-embedding-8b``), ``local`` → :class:`LocalEmbedder`
    (``Qwen/Qwen3-Embedding-0.6B``).
    """
    chosen = (provider or embed_provider()).lower()
    if chosen == "local":
        return LocalEmbedder(
            model or os.environ.get("ARASAAC_EMBED_MODEL") or DEFAULT_LOCAL_MODEL,
            device=device or os.environ.get("ARASAAC_EMBED_DEVICE") or None,
            query_instruction=query_instruction,
        )
    if chosen != "openai":
        raise EmbeddingError(f"unknown embedding provider: {chosen!r} (openai|local)")
    return OpenAIEmbedder(
        model or os.environ.get("ARASAAC_EMBED_MODEL") or DEFAULT_OPENAI_MODEL,
        base_url=base_url or os.environ.get("ARASAAC_EMBED_BASE_URL") or DEFAULT_OPENAI_BASE_URL,
        api_key=api_key if api_key is not None else embed_api_key(),
        batch_size=batch_size or embed_batch_size(),
        query_instruction=query_instruction,
        timeout=timeout,
        retries=retries if retries is not None else embed_int_env("ARASAAC_EMBED_RETRIES", 6),
        backoff=backoff or embed_float_env("ARASAAC_EMBED_BACKOFF", 2.0),
        min_interval=min_interval
        if min_interval is not None
        else embed_float_env("ARASAAC_EMBED_MIN_INTERVAL", 0.0),
    )


def embed_int_env(name: str, default: int) -> int:
    try:
        return int(os.environ.get(name, str(default)))
    except ValueError:
        return default


def embed_float_env(name: str, default: float) -> float:
    try:
        return float(os.environ.get(name, str(default)))
    except ValueError:
        return default


def embed_batch_size() -> int:
    """Texts per embedding request (``ARASAAC_EMBED_BATCH_SIZE``, default 64)."""
    try:
        return max(1, int(os.environ.get("ARASAAC_EMBED_BATCH_SIZE", "64")))
    except ValueError:
        return 64


def probe_dim(embedder: Embedder) -> int:
    """Vector dimensionality of ``embedder`` via a one-text probe."""
    (vector,) = embedder.embed(["pictogram"])
    return len(vector)


class OpenAIEmbedder:
    """Embeddings via an OpenAI-compatible ``/embeddings`` endpoint."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str = DEFAULT_OPENAI_BASE_URL,
        api_key: str | None = None,
        batch_size: int = 64,
        timeout: float = 60.0,
        retries: int = 3,
        backoff: float = 2.0,
        min_interval: float = 0.0,
        send_input_type: bool = True,
        query_instruction: str | None = None,
    ) -> None:
        self.model_name = model
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self.batch_size = max(1, batch_size)
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        #: Minimum seconds between requests (pacing against rate limits).
        self.min_interval = max(0.0, min_interval)
        self.send_input_type = send_input_type
        self.query_instruction = query_instruction
        self._last_request = 0.0

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> list[list[float]]:
        """Embed ``texts`` in batches; one vector per input, in input order."""
        if not texts:
            return []
        vectors: list[list[float]] = []
        for start in range(0, len(texts), self.batch_size):
            chunk = list(texts[start : start + self.batch_size])
            vectors.extend(
                self._embed_chunk(self._texts_for(chunk, is_query=is_query), is_query=is_query)
            )
        return vectors

    def _texts_for(self, texts: list[str], *, is_query: bool) -> list[str]:
        if is_query and self.query_instruction:
            return [f"{self.query_instruction}{text}" for text in texts]
        return texts

    def _embed_chunk(self, texts: list[str], *, is_query: bool = False) -> list[list[float]]:
        payload: dict[str, object] = {"model": self.model_name, "input": texts}
        if self.send_input_type:
            payload["input_type"] = "search_query" if is_query else "search_document"
        data = self._request(payload)
        items = data.get("data") if isinstance(data, dict) else None
        if not isinstance(items, list) or len(items) != len(texts):
            raise EmbeddingError(f"unexpected embeddings response for {len(texts)} input(s)")
        try:
            return [
                [float(value) for value in item["embedding"]]
                for item in sorted(items, key=lambda item: item.get("index", 0))
            ]
        except (KeyError, TypeError, ValueError) as exc:
            raise EmbeddingError(f"malformed embeddings response: {exc}") from exc

    def _request(self, payload: dict[str, object]) -> dict[str, object]:
        if self.api_key is None:
            raise EmbeddingError(
                "no embeddings API key; set ARASAAC_EMBED_API_KEY or OPENROUTER_API_KEY"
            )
        url = f"{self.base_url}/embeddings"
        body = json.dumps(payload).encode("utf-8")
        failures: list[str] = []
        attempt = 0
        for attempt in range(self.retries + 1):
            gap = self.min_interval - (time.monotonic() - self._last_request)
            if gap > 0:
                time.sleep(gap)
            self._last_request = time.monotonic()
            request = urllib.request.Request(
                url,
                data=body,
                headers={
                    "Content-Type": "application/json",
                    "Authorization": f"Bearer {self.api_key}",
                    "User-Agent": USER_AGENT,
                },
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as response:
                    return json.loads(response.read().decode("utf-8"))
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:200]
                failures.append(f"HTTP {exc.code}: {detail}")
                if exc.code not in (429, 500, 502, 503, 504):
                    break
            except (urllib.error.URLError, OSError, TimeoutError) as exc:
                failures.append(str(exc))
            if attempt < self.retries:
                time.sleep(self.backoff * (2**attempt))
        raise EmbeddingError(
            f"embedding request failed after {attempt + 1} attempt(s): " + "; ".join(failures)
        )


class LocalEmbedder:
    """Embeddings via a local ``sentence-transformers`` model (lazy import)."""

    def __init__(
        self,
        model: str = DEFAULT_LOCAL_MODEL,
        *,
        device: str | None = None,
        query_instruction: str | None = DEFAULT_QUERY_INSTRUCTION,
    ) -> None:
        self.model_name = model
        self.device = device
        self.query_instruction = query_instruction
        self._st_model: Any = None

    def _load(self) -> Any:
        """Instantiate the model lazily; ``sentence_transformers`` may be absent."""
        if self._st_model is None:
            try:
                from sentence_transformers import SentenceTransformer as Model
            except ImportError as exc:
                raise EmbeddingError(
                    "sentence-transformers is not installed "
                    "(install it as a dev dependency to use local embeddings)"
                ) from exc
            self._st_model = Model(self.model_name, device=self.device)
        return self._st_model

    def embed(self, texts: Sequence[str], *, is_query: bool = False) -> list[list[float]]:
        if not texts:
            return []
        model = self._load()
        if is_query and self.query_instruction:
            texts = [f"{self.query_instruction}{text}" for text in texts]
        vectors = model.encode(list(texts), convert_to_numpy=True)
        return [[float(value) for value in vector] for vector in vectors]
