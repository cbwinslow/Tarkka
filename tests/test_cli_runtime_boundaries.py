from __future__ import annotations

import argparse
import importlib
import runpy
import sys
from collections.abc import Callable
from pathlib import Path
from types import SimpleNamespace
from typing import cast
from uuid import UUID, uuid4

import pytest

from tarkka.domain.discovery import ProviderMode
from tarkka.domain.manifest import ResourceManifest
from tarkka.domain.models import Work
from tarkka.interfaces import cli
from tarkka.interfaces import main as main_interface
from tarkka.ports.works import WorkRepository


def test_package_main_entrypoint_returns_interface_main_status(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(main_interface, "main", lambda: 7)
    sys.modules.pop("tarkka.__main__", None)

    try:
        with pytest.raises(SystemExit) as raised:
            importlib.import_module("tarkka.__main__")
    finally:
        sys.modules.pop("tarkka.__main__", None)

    assert raised.value.code == 7


def test_cli_script_entrypoint_dispatches_and_exits(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    monkeypatch.delenv("TARKKA_WORK_BACKEND", raising=False)
    monkeypatch.setattr(sys, "argv", ["cli.py", "inspect", str(uuid4())])

    with pytest.raises(SystemExit) as raised:
        runpy.run_path(cli.__file__, run_name="__main__")

    assert raised.value.code == 2
    assert "document not found" in capsys.readouterr().err


def test_cli_home_and_work_repository_backend_selection(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("TARKKA_HOME", str(tmp_path))
    monkeypatch.delenv("TARKKA_WORK_BACKEND", raising=False)

    json_repository = cli._work_repository()
    assert json_repository.path == (tmp_path / "works.json").resolve()

    settings = object()
    postgres_repository = object()

    class _Settings:
        @staticmethod
        def from_environment() -> object:
            return settings

    monkeypatch.setattr(cli, "PostgresSettings", _Settings)
    monkeypatch.setattr(
        cli,
        "PostgresWorkRepository",
        lambda configured: postgres_repository if configured is settings else None,
    )
    monkeypatch.setenv("TARKKA_WORK_BACKEND", " POSTGRES ")
    assert cli._work_repository() is postgres_repository

    monkeypatch.setenv("TARKKA_WORK_BACKEND", "sqlite")
    with pytest.raises(ValueError, match="unsupported TARKKA_WORK_BACKEND"):
        cli._work_repository()


def test_cli_optional_docling_parser_is_added_only_when_available(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class _UnavailableDocling:
        @staticmethod
        def is_available() -> bool:
            return False

    monkeypatch.setattr(cli, "DoclingParser", _UnavailableDocling)
    without_docling = cli._parsers()
    assert len(without_docling) == 5

    class _AvailableDocling:
        @staticmethod
        def is_available() -> bool:
            return True

    monkeypatch.setattr(cli, "DoclingParser", _AvailableDocling)
    with_docling = cli._parsers()
    assert len(with_docling) == 6
    assert isinstance(with_docling[-1], _AvailableDocling)


def test_cli_discovery_provider_factories_forward_environment_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: list[tuple[str, dict[str, object]]] = []

    def provider_factory(name: str) -> Callable[..., SimpleNamespace]:
        def build(**kwargs: object) -> SimpleNamespace:
            captured.append((name, kwargs))
            return SimpleNamespace(name=name)

        return build

    monkeypatch.setenv("TARKKA_OPENALEX_API_KEY", "openalex-key")
    monkeypatch.setenv("TARKKA_CROSSREF_MAILTO", "research@example.test")
    monkeypatch.setenv("TARKKA_SEMANTIC_SCHOLAR_API_KEY", "s2-key")
    monkeypatch.setattr(cli, "OpenAlexProvider", provider_factory("openalex"))
    monkeypatch.setattr(cli, "CrossrefProvider", provider_factory("crossref"))
    monkeypatch.setattr(
        cli,
        "SemanticScholarProvider",
        provider_factory("semantic-scholar"),
    )
    monkeypatch.setattr(cli, "ArxivProvider", provider_factory("arxiv"))

    providers = cli._discovery_providers()
    crossref = cli._crossref()

    assert tuple(provider.name for provider in providers) == cli._PROVIDER_NAMES
    assert crossref.name == "crossref"
    assert captured == [
        ("openalex", {"api_key": "openalex-key"}),
        ("crossref", {"mailto": "research@example.test"}),
        ("semantic-scholar", {"api_key": "s2-key"}),
        ("arxiv", {}),
        ("crossref", {"mailto": "research@example.test"}),
    ]


def test_cli_manifest_yaml_preserves_manifest_blocks() -> None:
    manifest = ResourceManifest(
        resource_id="doc:example",
        kind="document",
        title='Quoted "title"',
        metadata={"source": "fixture"},
        available={"full_text": True},
        structure={"sections": 2},
        estimated_tokens={"manifest": 12},
    )

    rendered = cli._manifest_yaml(manifest)

    assert rendered.startswith("---\nid: doc:example\nkind: document\n")
    assert 'title: "Quoted \\"title\\""' in rendered
    assert "metadata:\n  source: \"fixture\"" in rendered
    assert "available:\n  full_text: true" in rendered
    assert "structure:\n  sections: 2" in rendered
    assert "tokens:\n  manifest: 12" in rendered
    assert rendered.endswith("---")


@pytest.mark.parametrize(
    ("parser", "prefix", "message"),
    [
        (cli._parse_document_id, "doc:", "invalid document id"),
        (cli._parse_work_id, "work:", "invalid work id"),
        (cli._parse_snapshot_id, "snapshot:", "invalid snapshot id"),
    ],
)
def test_cli_uuid_parsers_accept_handles_and_reject_invalid_values(
    parser: Callable[[str], UUID],
    prefix: str,
    message: str,
) -> None:
    identifier = uuid4()

    assert parser(f"{prefix}{identifier}") == identifier
    with pytest.raises(argparse.ArgumentTypeError, match=message):
        parser("not-a-uuid")


def test_cli_provider_policy_covers_auto_all_explicit_and_invalid_combinations() -> None:
    assert cli._provider_policy(None) == (ProviderMode.AUTO, ())
    assert cli._provider_policy(["all"]) == (ProviderMode.ALL, ())
    assert cli._provider_policy(["crossref", "arxiv"]) == (
        ProviderMode.ONLY,
        ("crossref", "arxiv"),
    )

    with pytest.raises(ValueError, match="auto.*cannot be combined"):
        cli._provider_policy(["auto", "crossref"])
    with pytest.raises(ValueError, match="all.*cannot be combined"):
        cli._provider_policy(["all", "crossref"])


def test_cli_provider_cursors_reject_unknown_provider() -> None:
    with pytest.raises(ValueError, match="unknown cursor provider"):
        cli._provider_cursors(["unknown=cursor"])


def test_cli_work_payload_groups_identifiers_and_source_providers() -> None:
    work = Work(
        work_id=uuid4(),
        title="Coverage fixture",
        publication_type="article",
        publication_year=2026,
        language="en",
        abstract="Present",
        venue="Test Journal",
    )

    class _Repository:
        def list_identifiers(self, work_id: UUID) -> list[SimpleNamespace]:
            assert work_id == work.work_id
            return [
                SimpleNamespace(scheme="doi", value="10.1/example"),
                SimpleNamespace(scheme="doi", value="10.1/alternate"),
                SimpleNamespace(scheme="arxiv", value="2608.00001"),
            ]

        def list_source_records(self, work_id: UUID) -> list[SimpleNamespace]:
            assert work_id == work.work_id
            return [
                SimpleNamespace(provider="crossref"),
                SimpleNamespace(provider="openalex"),
                SimpleNamespace(provider="crossref"),
            ]

    payload = cli._work_payload(work, cast(WorkRepository, _Repository()))

    assert payload["work_id"] == str(work.work_id)
    assert payload["abstract_available"] is True
    assert payload["identifiers"] == {
        "doi": ["10.1/example", "10.1/alternate"],
        "arxiv": ["2608.00001"],
    }
    assert payload["source_count"] == 3
    assert payload["source_providers"] == ["crossref", "openalex"]


def test_cli_work_payload_preserves_null_and_empty_metadata_shape() -> None:
    work = Work(work_id=uuid4(), title="Minimal work", abstract=None)

    class _Repository:
        def list_identifiers(self, work_id: UUID) -> list[SimpleNamespace]:
            assert work_id == work.work_id
            return []

        def list_source_records(self, work_id: UUID) -> list[SimpleNamespace]:
            assert work_id == work.work_id
            return []

    payload = cli._work_payload(work, cast(WorkRepository, _Repository()))

    assert payload["abstract_available"] is False
    assert payload["identifiers"] == {}
    assert payload["source_count"] == 0
    assert payload["source_providers"] == []
