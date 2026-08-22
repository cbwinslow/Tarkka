from __future__ import annotations

import hashlib
import json
from pathlib import Path
from uuid import uuid4

import pytest

from tarkka.application.bibliography import BibliographyImportService
from tarkka.application.works import WorkCatalogService, WorkIdentityConflictError
from tarkka.domain.models import Work
from tarkka.domain.work_identity import WorkIdentifier
from tarkka.infrastructure.bibliography_interchange import BibliographyParseError
from tarkka.infrastructure.storage.json_work_repository import JsonWorkRepository


def _service(tmp_path: Path) -> tuple[BibliographyImportService, JsonWorkRepository]:
    repository = JsonWorkRepository(tmp_path / "works.json")
    return BibliographyImportService(WorkCatalogService(repository)), repository


def test_reimporting_same_file_is_idempotent(tmp_path: Path) -> None:
    source = tmp_path / "refs.bib"
    source.write_text(
        "@article{smith2024, title={Stable Study}, year={2024}}\n",
        encoding="utf-8",
    )
    service, repository = _service(tmp_path)

    first = service.import_file(source)
    second = service.import_file(source)

    assert len(first.works) == 1
    assert second.works[0].work_id == first.works[0].work_id
    source_records = repository.list_source_records(first.works[0].work_id)
    assert len(source_records) == 1
    assert source_records[0].record.metadata["source_key"] == "smith2024"


def test_file_local_keys_do_not_merge_across_different_sources(tmp_path: Path) -> None:
    first_source = tmp_path / "first.bib"
    second_source = tmp_path / "second.bib"
    first_source.write_text(
        "@article{smith2024, title={First Study}, year={2024}}\n",
        encoding="utf-8",
    )
    second_source.write_text(
        "@article{smith2024, title={Different Study}, year={2024}}\n",
        encoding="utf-8",
    )
    service, _ = _service(tmp_path)

    first = service.import_file(first_source)
    second = service.import_file(second_source)

    assert first.source_sha256 != second.source_sha256
    assert first.works[0].work_id != second.works[0].work_id


def test_duplicate_native_keys_fail_closed_before_persistence(tmp_path: Path) -> None:
    source = tmp_path / "duplicates.bib"
    source.write_text(
        "@article{same, title={First Study}}\n"
        "@article{same, title={Different Study}}\n",
        encoding="utf-8",
    )
    service, repository = _service(tmp_path)

    with pytest.raises(BibliographyParseError, match="duplicate bibliography source key"):
        service.import_file(source)

    catalog = json.loads(repository.path.read_text(encoding="utf-8"))
    assert catalog["works"] == {}
    assert catalog["identifiers"] == {}
    assert catalog["source_records"] == {}


def test_strong_doi_reconciles_across_bibliography_formats(tmp_path: Path) -> None:
    bib = tmp_path / "refs.bib"
    ris = tmp_path / "refs.ris"
    bib.write_text(
        "@article{local-a, title={Shared Study}, doi={10.1000/shared}, year={2024}}\n",
        encoding="utf-8",
    )
    ris.write_text(
        "TY  - JOUR\nID  - local-b\nTI  - Shared Study\nPY  - 2024\n"
        "DO  - https://doi.org/10.1000/shared\nER  -\n",
        encoding="utf-8",
    )
    service, repository = _service(tmp_path)

    first = service.import_file(bib)
    second = service.import_file(ris)

    assert first.works[0].work_id == second.works[0].work_id
    source_records = repository.list_source_records(first.works[0].work_id)
    assert {record.provider for record in source_records} == {
        "bibliography:bibtex",
        "bibliography:ris",
    }
    identifiers = repository.list_identifiers(first.works[0].work_id)
    assert ("doi", "10.1000/shared") in {
        (identifier.scheme, identifier.value) for identifier in identifiers
    }


def test_late_identity_conflict_rolls_back_entire_import_batch(tmp_path: Path) -> None:
    source = tmp_path / "atomic.bib"
    content = (
        "@article{new-first, title={Would Be Partial}}\n"
        "@article{conflicting, title={Conflicting Study}, doi={10.1000/conflict}}\n"
    )
    source.write_text(content, encoding="utf-8")
    source_sha256 = hashlib.sha256(content.encode("utf-8")).hexdigest()
    service, repository = _service(tmp_path)

    doi_owner = Work(work_id=uuid4(), title="DOI owner")
    provider_owner = Work(work_id=uuid4(), title="Provider owner")
    with repository.transaction():
        repository.save_work(doi_owner)
        repository.save_work(provider_owner)
        repository.save_identifier(
            WorkIdentifier(
                identifier_id=uuid4(),
                work_id=doi_owner.work_id,
                scheme="doi",
                value="10.1000/conflict",
            )
        )
        repository.save_identifier(
            WorkIdentifier(
                identifier_id=uuid4(),
                work_id=provider_owner.work_id,
                scheme="bibliography:bibtex",
                value=f"{source_sha256}:conflicting",
            )
        )

    with pytest.raises(WorkIdentityConflictError, match="multiple canonical Works"):
        service.import_file(source)

    catalog = json.loads(repository.path.read_text(encoding="utf-8"))
    assert set(catalog["works"]) == {str(doi_owner.work_id), str(provider_owner.work_id)}
    assert repository.find_work_by_identifier(
        "bibliography:bibtex",
        f"{source_sha256}:new-first",
    ) is None
