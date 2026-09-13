from __future__ import annotations

from pathlib import Path
from uuid import UUID

import pytest

import tarkka.infrastructure.sentence_transformer_embeddings as embedding_module
from tarkka.domain.models import Passage
from tarkka.domain.retrieval import RetrievalPassageSpan, RetrievalSegment
from tarkka.infrastructure.sentence_transformer_embeddings import (
    LocalSentenceTransformerEmbedder,
    SentenceTransformerUnavailableError,
)


class _Model:
    def __init__(self, values: tuple[object, ...] = (0.6, 0.8)) -> None:
        self.values = values
        self.calls: list[tuple[str, bool]] = []

    def encode(self, sentences: str, *, normalize_embeddings: bool) -> tuple[object, ...]:
        self.calls.append((sentences, normalize_embeddings))
        return self.values


def _segment() -> RetrievalSegment:
    passage = Passage(UUID(int=1), UUID(int=2), UUID(int=3), 0, "local text", 0, 10)
    return RetrievalSegment.from_passages(
        passages=(passage,),
        source_spans=(RetrievalPassageSpan(passage.section_id, passage.passage_id, 0, 10),),
        derivation_version="v1",
        configuration_fingerprint="f1",
    )


def test_embedder_records_pinned_provenance_and_requests_normalization() -> None:
    model = _Model()
    embedder = LocalSentenceTransformerEmbedder(model, "model", "revision", "configuration")

    embedding = embedder.embed(_segment())
    query = embedder.embed_query(UUID(int=9), "query")

    assert embedding.model_identifier == "model"
    assert embedding.model_revision == "revision"
    assert embedding.values == (0.6, 0.8)
    assert query.query_id == UUID(int=9)
    assert model.calls == [("local text", True), ("query", True)]


@pytest.mark.parametrize("value", ["", " ", None])
def test_embedder_rejects_blank_provenance(value: object) -> None:
    with pytest.raises(ValueError, match="non-blank"):
        LocalSentenceTransformerEmbedder(_Model(), value, "revision", "configuration")  # type: ignore[arg-type]


def test_embedder_fails_closed_for_invalid_source_and_model_failure() -> None:
    embedder = LocalSentenceTransformerEmbedder(_Model(("bad",)), "model", "revision", "config")
    with pytest.raises(ValueError, match="RetrievalSegment"):
        embedder.embed(object())  # type: ignore[arg-type]
    with pytest.raises(SentenceTransformerUnavailableError, match="local embedding failed"):
        embedder.embed(_segment())
    zero = LocalSentenceTransformerEmbedder(_Model((0.0, 0.0)), "model", "revision", "config")
    with pytest.raises(SentenceTransformerUnavailableError, match="local embedding failed"):
        zero.embed(_segment())


def test_local_path_requires_existing_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="existing directory"):
        LocalSentenceTransformerEmbedder.from_local_path(
            tmp_path / "missing",
            model_identifier="model",
            model_revision="revision",
            configuration_fingerprint="configuration",
        )


def test_local_path_fails_closed_when_runtime_or_model_load_is_unavailable(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    model_path = tmp_path / "model"
    model_path.mkdir()
    monkeypatch.setattr(
        embedding_module, "import_module", lambda _: (_ for _ in ()).throw(ImportError())
    )
    with pytest.raises(SentenceTransformerUnavailableError, match="install"):
        LocalSentenceTransformerEmbedder.from_local_path(
            model_path,
            model_identifier="model",
            model_revision="revision",
            configuration_fingerprint="configuration",
        )

    class _Module:
        @staticmethod
        def SentenceTransformer(*_: object, **__: object) -> object:
            raise RuntimeError("bad local model")

    monkeypatch.setattr(embedding_module, "import_module", lambda _: _Module())
    with pytest.raises(SentenceTransformerUnavailableError, match="unable to load"):
        LocalSentenceTransformerEmbedder.from_local_path(
            model_path,
            model_identifier="model",
            model_revision="revision",
            configuration_fingerprint="configuration",
        )

    class _GoodModule:
        @staticmethod
        def SentenceTransformer(*_: object, **__: object) -> _Model:
            return _Model()

    monkeypatch.setattr(embedding_module, "import_module", lambda _: _GoodModule())
    assert (
        LocalSentenceTransformerEmbedder.from_local_path(
            model_path,
            model_identifier="model",
            model_revision="revision",
            configuration_fingerprint="configuration",
        ).model_identifier
        == "model"
    )
