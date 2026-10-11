"""The embeddings layer (:mod:`arasaac_mcp.embeddings`), offline.

The OpenAI-compatible client is exercised against a stubbed ``urllib``; the
local ``sentence-transformers`` model is only tested for its failure path (the
library itself is deliberately not downloaded in tests).
"""

from __future__ import annotations

import io
import json
import sys
import urllib.error

import pytest

from arasaac_mcp.embeddings import (
    DEFAULT_LOCAL_MODEL,
    DEFAULT_OPENAI_MODEL,
    EmbeddingError,
    LocalEmbedder,
    OpenAIEmbedder,
    embed_api_key,
    embed_batch_size,
    make_embedder,
    probe_dim,
)


class _FakeResponse:
    """A context-manager stand-in for ``urllib.request``'s response."""

    def __init__(self, payload: dict) -> None:
        self._data = json.dumps(payload).encode("utf-8")

    def read(self) -> bytes:
        return self._data

    def __enter__(self) -> _FakeResponse:
        return self

    def __exit__(self, *args: object) -> None:
        return None


def _ok_payload(chunk: list[str]) -> dict:
    return {
        "data": [
            {"index": index, "object": "embedding", "embedding": [float(len(chunk)), index]}
            for index, text in enumerate(chunk)
        ]
    }


def _install_urlopen(monkeypatch: pytest.MonkeyPatch, responses: list[dict]) -> list[dict]:
    """Replace ``urllib.request.urlopen`` with payloads from ``responses``."""
    calls: list[dict] = []

    def fake_urlopen(request, timeout=None):
        body = json.loads(request.data.decode("utf-8"))
        calls.append(body)
        response = responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return _FakeResponse(response)

    monkeypatch.setattr("urllib.request.urlopen", fake_urlopen)
    return calls


def test_openai_embedder_batches(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_urlopen(monkeypatch, [_ok_payload(["a", "b"]), _ok_payload(["c"])])
    embedder = OpenAIEmbedder("test-model", api_key="key", batch_size=2, send_input_type=False)
    vectors = embedder.embed(["a", "b", "c"], is_query=True)
    assert [len(request["input"]) for request in calls] == [2, 1]
    assert all(request["model"] == "test-model" for request in calls)
    assert not any("input_type" in request for request in calls)
    assert vectors == [[2.0, 0.0], [2.0, 1.0], [1.0, 0.0]]


def test_openai_embedder_reorders_by_index(monkeypatch: pytest.MonkeyPatch) -> None:
    payload = {
        "data": [
            {"index": 1, "embedding": [2.0]},
            {"index": 0, "embedding": [1.0]},
        ]
    }
    _install_urlopen(monkeypatch, [payload])
    embedder = OpenAIEmbedder("test-model", api_key="key", send_input_type=False)
    assert embedder.embed(["x", "y"]) == [[1.0], [2.0]]


def test_openai_embedder_input_type(monkeypatch: pytest.MonkeyPatch) -> None:
    calls = _install_urlopen(
        monkeypatch, [_ok_payload(["document"]), {"data": [{"index": 0, "embedding": [1.0]}]}]
    )
    embedder = OpenAIEmbedder("test-model", api_key="key")
    embedder.embed(["document"])
    embedder.embed(["question"], is_query=True)
    assert calls[0]["input_type"] == "search_document"
    assert calls[1]["input_type"] == "search_query"


def test_openai_embedder_query_instruction() -> None:
    embedder = OpenAIEmbedder("test-model", api_key="key", query_instruction="Q: ")
    assert embedder._texts_for(["nose"], is_query=False) == ["nose"]
    assert embedder._texts_for(["nose"], is_query=True) == ["Q: nose"]


def test_openai_embedder_empty_input(monkeypatch: pytest.MonkeyPatch) -> None:
    installed = _install_urlopen(monkeypatch, [])
    embedder = OpenAIEmbedder("test-model", api_key="key")
    assert embedder.embed([]) == []
    assert not installed


def test_openai_embedder_without_key() -> None:
    embedder = OpenAIEmbedder("test-model", api_key=None)
    with pytest.raises(EmbeddingError, match="API key"):
        embedder.embed(["nose"])


def test_openai_embedder_http_error(monkeypatch: pytest.MonkeyPatch) -> None:
    error = urllib.error.HTTPError(
        "https://example.invalid/v1/embeddings",
        400,
        "Bad Request",
        hdrs=None,
        fp=io.BytesIO(b'{"error": "no"}'),
    )
    _install_urlopen(monkeypatch, [error])
    embedder = OpenAIEmbedder("test-model", api_key="key", retries=0)
    with pytest.raises(EmbeddingError, match="HTTP 400"):
        embedder.embed(["nose"])


def test_openai_embedder_retries_on_rate_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr("time.sleep", lambda seconds: None)
    calls = _install_urlopen(
        monkeypatch,
        [
            urllib.error.HTTPError("u", 429, "rate", hdrs=None, fp=io.BytesIO(b"")),
            _ok_payload(["a"]),
        ],
    )
    embedder = OpenAIEmbedder("test-model", api_key="key", send_input_type=False)
    assert embedder.embed(["a"]) == [[1.0, 0.0]]
    assert len(calls) == 2


def test_openai_embedder_malformed_response(monkeypatch: pytest.MonkeyPatch) -> None:
    _install_urlopen(monkeypatch, [{"data": []}])
    embedder = OpenAIEmbedder("test-model", api_key="key", send_input_type=False)
    with pytest.raises(EmbeddingError, match="response"):
        embedder.embed(["a"])


@pytest.fixture
def no_embedding_config(monkeypatch: pytest.MonkeyPatch) -> None:
    for name in (
        "ARASAAC_EMBED_PROVIDER",
        "ARASAAC_EMBED_MODEL",
        "ARASAAC_EMBED_API_KEY",
        "OPENROUTER_API_KEY",
        "ARASAAC_EMBED_BASE_URL",
        "ARASAAC_EMBED_DEVICE",
        "ARASAAC_EMBED_BATCH_SIZE",
    ):
        monkeypatch.delenv(name, raising=False)


def test_embed_api_key_prefers_arasaac_var(
    no_embedding_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert embed_api_key() is None
    monkeypatch.setenv("OPENROUTER_API_KEY", "or")
    assert embed_api_key() == "or"
    monkeypatch.setenv("ARASAAC_EMBED_API_KEY", "aa")
    assert embed_api_key() == "aa"


def test_embed_batch_size_default_and_env(
    no_embedding_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert embed_batch_size() == 64
    monkeypatch.setenv("ARASAAC_EMBED_BATCH_SIZE", "128")
    assert embed_batch_size() == 128
    monkeypatch.setenv("ARASAAC_EMBED_BATCH_SIZE", "nope")
    assert embed_batch_size() == 64


def test_make_embedder_openai_default(no_embedding_config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "key")
    embedder = make_embedder()
    assert embedder.model_name == DEFAULT_OPENAI_MODEL


def test_make_embedder_local(no_embedding_config) -> None:
    embedder = make_embedder("local")
    assert isinstance(embedder, LocalEmbedder)
    assert embedder.model_name == DEFAULT_LOCAL_MODEL


def test_make_embedder_local_import_fails(
    no_embedding_config, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(sys.modules, "sentence_transformers", None)
    with pytest.raises(EmbeddingError, match="sentence-transformers"):
        LocalEmbedder().embed(["x"])


def test_make_embedder_unknown_provider(no_embedding_config) -> None:
    with pytest.raises(EmbeddingError, match="provider"):
        make_embedder("wasabi")


def test_probe_dim(no_embedding_config, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("OPENROUTER_API_KEY", raising=False)
    embedder = OpenAIEmbedder("test-model", api_key="key", send_input_type=False)
    calls = _install_urlopen(monkeypatch, [{"data": [{"index": 0, "embedding": [0.5] * 7}]}])
    assert probe_dim(embedder) == 7
    assert len(calls) == 1
