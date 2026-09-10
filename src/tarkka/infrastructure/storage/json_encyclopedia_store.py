"""Local JSON persistence for encyclopedia editions."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, cast
from uuid import UUID

from tarkka.application.encyclopedia import EncyclopediaArticle, EncyclopediaEdition
from tarkka.infrastructure.storage.locking import exclusive_lock


class JsonEncyclopediaStore:
    def __init__(self, path: Path) -> None:
        self.path = path.expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with exclusive_lock(self.path):
            if not self.path.exists():
                self._write({"schema_version": 1, "editions": {}})

    def save_edition(self, edition: EncyclopediaEdition) -> None:
        with exclusive_lock(self.path):
            data = self._read()
            editions = cast(dict[str, Any], data["editions"])
            editions[str(edition.edition_id)] = _edition_to_dict(edition)
            self._write(data)

    def get_edition(self, edition_id: UUID) -> EncyclopediaEdition | None:
        with exclusive_lock(self.path):
            payload = cast(dict[str, Any], self._read()["editions"]).get(str(edition_id))
        if payload is None:
            return None
        return _edition_from_dict(payload)

    def get_article(self, article_id: UUID) -> EncyclopediaArticle | None:
        with exclusive_lock(self.path):
            editions = cast(dict[str, Any], self._read()["editions"])
        for payload in editions.values():
            edition = _edition_from_dict(payload)
            for article in edition.articles:
                if article.article_id == article_id:
                    return article
        return None

    def _read(self) -> dict[str, Any]:
        try:
            decoded: Any = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"unable to read encyclopedia store {self.path}: {exc}") from exc
        if not isinstance(decoded, dict) or decoded.get("schema_version") != 1:
            raise RuntimeError("unsupported encyclopedia store schema")
        if not isinstance(decoded.get("editions"), dict):
            raise RuntimeError("invalid encyclopedia store: editions must be a JSON object")
        return cast(dict[str, Any], decoded)

    def _write(self, data: dict[str, Any]) -> None:
        fd, temp_name = tempfile.mkstemp(prefix=".tarkka-encyclopedia-", dir=self.path.parent)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(data, handle, indent=2, sort_keys=True)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temp_path, self.path)
        except Exception:
            temp_path.unlink(missing_ok=True)
            raise


def _edition_to_dict(edition: EncyclopediaEdition) -> dict[str, Any]:
    return {
        "edition_id": str(edition.edition_id),
        "workspace_id": str(edition.workspace_id),
        "compiler_name": edition.compiler_name,
        "compiler_version": edition.compiler_version,
        "snapshot_handle": edition.snapshot_handle,
        "redistribution_allowed": edition.redistribution_allowed,
        "compiled_at": edition.compiled_at.isoformat(),
        "articles": [_article_to_dict(item) for item in edition.articles],
    }


def _article_to_dict(article: EncyclopediaArticle) -> dict[str, Any]:
    return {
        "article_id": str(article.article_id),
        "edition_id": str(article.edition_id),
        "topic_id": article.topic_id,
        "title": article.title,
        "claim_ids": [str(item) for item in article.claim_ids],
        "contradiction_count": article.contradiction_count,
        "body_markdown": article.body_markdown,
        "body_sha256": article.body_sha256,
        "estimated_tokens": article.estimated_tokens,
    }


def _edition_from_dict(payload: dict[str, Any]) -> EncyclopediaEdition:
    try:
        articles = tuple(_article_from_dict(item) for item in payload["articles"])
        return EncyclopediaEdition(
            edition_id=UUID(payload["edition_id"]),
            workspace_id=UUID(payload["workspace_id"]),
            compiler_name=str(payload["compiler_name"]),
            compiler_version=str(payload["compiler_version"]),
            snapshot_handle=str(payload["snapshot_handle"]),
            redistribution_allowed=bool(payload["redistribution_allowed"]),
            compiled_at=datetime.fromisoformat(payload["compiled_at"]),
            articles=articles,
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise RuntimeError(f"invalid encyclopedia edition: {exc}") from exc


def _article_from_dict(payload: dict[str, Any]) -> EncyclopediaArticle:
    return EncyclopediaArticle(
        article_id=UUID(payload["article_id"]),
        edition_id=UUID(payload["edition_id"]),
        topic_id=str(payload["topic_id"]),
        title=str(payload["title"]),
        claim_ids=tuple(UUID(item) for item in payload["claim_ids"]),
        contradiction_count=int(payload["contradiction_count"]),
        body_markdown=str(payload["body_markdown"]),
        body_sha256=str(payload["body_sha256"]),
        estimated_tokens={
            str(key): int(value) for key, value in dict(payload["estimated_tokens"]).items()
        },
    )
