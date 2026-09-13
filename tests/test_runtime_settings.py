from __future__ import annotations

from pathlib import Path

import pytest

from tarkka.runtime.settings import (
    TarkkaSettings,
    resolve_document_backend,
    resolve_work_backend,
)


def test_home_defaults_to_dot_tarkka(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARKKA_HOME", raising=False)
    settings = TarkkaSettings.from_environment()
    assert settings.home == Path("~/.tarkka").expanduser().resolve()


def test_home_honors_explicit_environment_value(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    assert TarkkaSettings.from_environment().home == tmp_path.expanduser().resolve()


def test_document_backend_defaults_to_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert resolve_document_backend() == "json"


def test_document_backend_strips_and_lowercases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", " Postgres ")
    assert resolve_document_backend() == "postgres"


def test_document_backend_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_DOCUMENT_BACKEND", "sqlite")
    with pytest.raises(ValueError, match="unsupported TARKKA_DOCUMENT_BACKEND 'sqlite'"):
        resolve_document_backend()


def test_work_backend_defaults_to_json(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("TARKKA_WORK_BACKEND", raising=False)
    assert resolve_work_backend() == "json"


def test_work_backend_strips_and_lowercases(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", " Postgres ")
    assert resolve_work_backend() == "postgres"


def test_work_backend_rejects_unknown_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("TARKKA_WORK_BACKEND", "sqlite")
    with pytest.raises(ValueError, match="unsupported TARKKA_WORK_BACKEND 'sqlite'"):
        resolve_work_backend()


def test_document_and_work_backend_are_resolved_independently(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An invalid value for one backend variable must never affect the other."""
    monkeypatch.setenv("TARKKA_WORK_BACKEND", "sqlite")
    monkeypatch.delenv("TARKKA_DOCUMENT_BACKEND", raising=False)
    assert resolve_document_backend() == "json"
    with pytest.raises(ValueError, match="unsupported TARKKA_WORK_BACKEND"):
        resolve_work_backend()
