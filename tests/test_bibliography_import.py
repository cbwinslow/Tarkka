from __future__ import annotations

from pathlib import Path

from tarkka.application.bibliography import BibliographyImportService
from tarkka.application.works import WorkCatalogService
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
