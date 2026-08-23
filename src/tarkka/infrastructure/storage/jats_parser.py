from __future__ import annotations

from collections.abc import Iterable, Iterator
from pathlib import Path
from uuid import NAMESPACE_URL, UUID, uuid5
from xml.etree import ElementTree as ET

from tarkka.domain.citations import BibliographicReference, CitationMention
from tarkka.domain.models import Artifact, Document, Passage, Section
from tarkka.domain.source_artifacts import Equation, Figure, Table
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ObservationBasis,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)
from tarkka.ports.parsing import NativeDocumentParseResult

_XLINK_HREF = "{http://www.w3.org/1999/xlink}href"
_PASSAGE_BLOCK_ELEMENTS = frozenset({"p", "disp-quote", "boxed-text", "list", "def-list"})
# Structural content is represented elsewhere (or intentionally excluded) and must not be
# duplicated into parent passage text, including when nested inside paragraphs/list items.
_PASSAGE_STRUCTURAL_ELEMENTS = frozenset(
    {
        "title",
        "label",
        "sec-meta",
        "sec",
        "fig",
        "fig-group",
        "table-wrap",
        "table-wrap-group",
        "disp-formula",
        "disp-formula-group",
        "supplementary-material",
        "ref-list",
        "fn-group",
        "glossary",
        "media",
        "graphic",
    }
)


class JatsParser:
    """Preserve JATS article structure directly instead of flattening through Markdown."""

    name = "jats"
    version = "1"
    manifest = CapabilityManifest(
        adapter_name=name,
        adapter_kind=AdapterKind.PARSER,
        version=version,
        capabilities=frozenset(
            {
                Capability.PARSE,
                Capability.FULL_TEXT,
                Capability.NATIVE_METADATA,
                Capability.DOCUMENT_METADATA,
                Capability.DOCUMENT_STRUCTURE,
                Capability.BIBLIOGRAPHY,
                Capability.INLINE_CITATIONS,
                Capability.FIGURES,
                Capability.TABLES,
                Capability.EQUATIONS,
                Capability.SUPPLEMENTS,
                Capability.LINK_DISCOVERY,
            }
        ),
        media_types=frozenset({"application/jats+xml", "application/xml", "text/xml"}),
        identifier_schemes=frozenset({"doi", "pmid", "pmcid", "publisher-id"}),
    )

    def supports(self, artifact: Artifact) -> bool:
        if artifact.media_type in self.manifest.media_types:
            return True
        if artifact.original_name is None:
            return False
        return Path(artifact.original_name).suffix.lower() in {".nxml", ".jats"}

    def parse(self, artifact: Artifact, path: Path) -> Document:
        return self.parse_native(artifact, path).document

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult:
        try:
            root = ET.parse(path).getroot()
        except (ET.ParseError, OSError) as exc:
            raise ValueError(f"unable to parse JATS XML {path}: {exc}") from exc
        if _local_name(root.tag) != "article":
            raise ValueError("JATS parser requires an <article> root element")
        _strip_element_namespaces(root)

        document_id = _stable_id(artifact.artifact_id, "document")
        observation_id = _stable_id(artifact.artifact_id, "observation")
        title = _text(root.find("./front/article-meta/title-group/article-title"))
        if not title:
            title = artifact.original_name or "Document"

        sections = _sections(root, document_id, title)
        figures = _figures(root, document_id)
        tables = _tables(root, document_id)
        equations = _equations(root, document_id)
        document = Document(
            document_id=document_id,
            artifact_id=artifact.artifact_id,
            title=title,
            parser_name=self.name,
            parser_version=self.version,
            sections=sections,
            figures=figures,
            tables=tables,
            equations=equations,
        )
        references, reference_targets = _references(root, document_id, observation_id)
        mentions = _mentions(root, document_id, observation_id, reference_targets)
        resource_links = _resource_links(root, observation_id, artifact.artifact_id)
        observation = SourceObservation(
            observation_id=observation_id,
            source_name=self.name,
            source_version=self.version,
            basis=ObservationBasis.NATIVE,
            media_type=artifact.media_type,
            native_artifact_id=artifact.artifact_id,
            provider_record_id=_article_identifier(root),
            metadata={
                "article_type": root.attrib.get("article-type"),
                "journal_title": _text(
                    root.find("./front/journal-meta/journal-title-group/journal-title")
                ),
                "article_ids": _article_ids(root),
                "native_section_ids": _native_ids(root.findall(".//sec")),
                "native_figure_ids": _native_ids(root.findall(".//fig")),
                "native_table_ids": _native_ids(root.findall(".//table-wrap")),
                "native_equation_ids": _native_ids(root.findall(".//disp-formula")),
                "counts": {
                    "sections": len(sections),
                    "figures": len(figures),
                    "tables": len(tables),
                    "equations": len(equations),
                    "references": len(references),
                    "citation_mentions": len(mentions),
                    "resource_links": len(resource_links),
                },
            },
        )
        return NativeDocumentParseResult(
            document=document,
            observation=observation,
            references=references,
            mentions=mentions,
            resource_links=resource_links,
        )


def _sections(root: ET.Element, document_id: UUID, fallback_title: str) -> tuple[Section, ...]:
    specs: list[tuple[ET.Element | None, str, int, UUID | None, tuple[str, ...]]] = []
    abstract = root.find("./front/article-meta/abstract")
    if abstract is not None:
        abstract_paragraphs = tuple(_direct_content_texts(abstract))
        if abstract_paragraphs:
            abstract_title = _text(abstract.find("./title")) or "Abstract"
            specs.append((abstract, abstract_title, 1, None, abstract_paragraphs))

    def walk(element: ET.Element, level: int, parent_id: UUID | None) -> None:
        native_id = element.attrib.get("id")
        ordinal = len(specs)
        section_id = _stable_id(
            document_id,
            f"section:{ordinal}:{native_id or 'unanchored'}",
        )
        title = _text(element.find("./title")) or f"Section {ordinal + 1}"
        paragraphs = tuple(_direct_content_texts(element))
        specs.append((element, title, level, parent_id, paragraphs))
        for child in element.findall("./sec"):
            walk(child, level + 1, section_id)

    body = root.find("./body")
    if body is not None:
        body_sections = body.findall("./sec")
        if body_sections:
            for section in body_sections:
                walk(section, 1, None)
        else:
            paragraphs = tuple(_direct_content_texts(body))
            if paragraphs:
                specs.append((body, fallback_title, 1, None, paragraphs))

    sections: list[Section] = []
    cursor = 0
    for ordinal, (element, title, level, parent_id, paragraphs) in enumerate(specs):
        native_id = element.attrib.get("id") if element is not None else None
        section_id = _stable_id(
            document_id,
            f"section:{ordinal}:{native_id or 'unanchored'}",
        )
        passages: list[Passage] = []
        for passage_ordinal, text in enumerate(paragraphs):
            start = cursor
            end = start + len(text)
            passages.append(
                Passage(
                    passage_id=_stable_id(section_id, f"passage:{passage_ordinal}"),
                    document_id=document_id,
                    section_id=section_id,
                    ordinal=passage_ordinal,
                    text=text,
                    char_start=start,
                    char_end=end,
                )
            )
            cursor = end + 1
        sections.append(
            Section(
                section_id=section_id,
                document_id=document_id,
                ordinal=ordinal,
                title=title,
                level=level,
                parent_section_id=parent_id,
                passages=tuple(passages),
            )
        )
    return tuple(sections)


def _direct_content_texts(container: ET.Element) -> Iterable[str]:
    mixed_parts: list[str] = []
    _append_mixed_text(mixed_parts, container.text)

    for child in container:
        name = _local_name(child.tag)
        if name in _PASSAGE_BLOCK_ELEMENTS:
            yield from _flush_mixed_parts(mixed_parts)
            if name == "list":
                items = child.findall("./list-item")
            elif name == "def-list":
                items = child.findall("./def-item")
            else:
                items = ()

            if items:
                for item in items:
                    text = _passage_text(item)
                    if text:
                        yield text
            elif name not in {"list", "def-list"}:
                text = _passage_text(child)
                if text:
                    yield text
        elif name in _PASSAGE_STRUCTURAL_ELEMENTS:
            yield from _flush_mixed_parts(mixed_parts)
        else:
            _append_mixed_text(mixed_parts, _passage_text(child))

        # XML tail text is content in the parent immediately after this child.
        _append_mixed_text(mixed_parts, child.tail)

    yield from _flush_mixed_parts(mixed_parts)


def _passage_text(element: ET.Element) -> str:
    """Extract passage text while excluding nested structural artifact content."""
    parts: list[str] = []
    _append_mixed_text(parts, element.text)
    for child in element:
        if _local_name(child.tag) not in _PASSAGE_STRUCTURAL_ELEMENTS:
            _append_mixed_text(parts, _passage_text(child))
        _append_mixed_text(parts, child.tail)
    return _normalize_mixed_text(parts)


def _append_mixed_text(parts: list[str], value: str | None) -> None:
    if value is not None:
        parts.append(value)


def _normalize_mixed_text(parts: Iterable[str]) -> str:
    """Collapse source whitespace without inventing separators between adjacent inline nodes."""
    return " ".join("".join(parts).split())


def _flush_mixed_parts(parts: list[str]) -> Iterator[str]:
    if not parts:
        return
    text = _normalize_mixed_text(parts)
    parts.clear()
    if text:
        yield text


def _figures(root: ET.Element, document_id: UUID) -> tuple[Figure, ...]:
    values: list[Figure] = []
    for ordinal, element in enumerate(root.findall(".//fig")):
        native_id = element.attrib.get("id")
        values.append(
            Figure(
                figure_id=_stable_id(
                    document_id,
                    f"figure:{ordinal}:{native_id or 'unanchored'}",
                ),
                document_id=document_id,
                ordinal=ordinal,
                label=_text(element.find("./label")) or None,
                caption=_text(element.find("./caption")) or None,
                figure_type=element.attrib.get("fig-type", "unknown"),
            )
        )
    return tuple(values)


def _tables(root: ET.Element, document_id: UUID) -> tuple[Table, ...]:
    values: list[Table] = []
    for ordinal, element in enumerate(root.findall(".//table-wrap")):
        native_id = element.attrib.get("id")
        rows = element.findall(".//tr")
        column_count = max((_row_column_count(row) for row in rows), default=0)
        values.append(
            Table(
                table_id=_stable_id(
                    document_id,
                    f"table:{ordinal}:{native_id or 'unanchored'}",
                ),
                document_id=document_id,
                ordinal=ordinal,
                label=_text(element.find("./label")) or None,
                caption=_text(element.find("./caption")) or None,
                row_count=len(rows),
                column_count=column_count,
            )
        )
    return tuple(values)


def _row_column_count(row: ET.Element) -> int:
    count = 0
    for cell in (*row.findall("./th"), *row.findall("./td")):
        raw_colspan = cell.attrib.get("colspan", "1")
        try:
            colspan = int(raw_colspan)
        except ValueError as exc:
            raise ValueError(f"invalid JATS table colspan: {raw_colspan!r}") from exc
        if colspan < 1:
            raise ValueError(f"invalid JATS table colspan: {raw_colspan!r}")
        count += colspan
    return count


def _equations(root: ET.Element, document_id: UUID) -> tuple[Equation, ...]:
    values: list[Equation] = []
    for ordinal, element in enumerate(root.findall(".//disp-formula")):
        native_id = element.attrib.get("id")
        source = _text(element.find(".//tex-math"))
        if not source:
            math = element.find(".//math")
            source = _text(math)
        if not source:
            source = _text(element)
        values.append(
            Equation(
                equation_id=_stable_id(
                    document_id,
                    f"equation:{ordinal}:{native_id or 'unanchored'}",
                ),
                document_id=document_id,
                ordinal=ordinal,
                label=_text(element.find("./label")) or None,
                source_text=source or None,
            )
        )
    return tuple(values)


def _references(
    root: ET.Element,
    document_id: UUID,
    observation_id: UUID,
) -> tuple[tuple[BibliographicReference, ...], dict[str, UUID]]:
    values: list[BibliographicReference] = []
    targets: dict[str, UUID] = {}
    for ordinal, element in enumerate(root.findall(".//ref-list/ref")):
        native_id = element.attrib.get("id")
        reference_id = _stable_id(
            document_id,
            f"reference:{ordinal}:{native_id or 'unanchored'}",
        )
        if native_id:
            if native_id in targets:
                raise ValueError(f"duplicate JATS bibliography native ID: {native_id}")
            targets[native_id] = reference_id
        identifiers: dict[str, str] = {}
        for pub_id in element.findall(".//pub-id"):
            scheme = pub_id.attrib.get("pub-id-type", "").strip().lower()
            value = _text(pub_id)
            if scheme and value:
                identifiers[scheme] = value
        values.append(
            BibliographicReference(
                reference_id=reference_id,
                document_id=document_id,
                ordinal=ordinal,
                raw_text=_text(element) or f"Reference {ordinal + 1}",
                identifiers=identifiers,
                title=_text(element.find(".//article-title")) or None,
                source_anchor=native_id,
                source_observation_id=observation_id,
            )
        )
    return tuple(values), targets


def _mentions(
    root: ET.Element,
    document_id: UUID,
    observation_id: UUID,
    reference_targets: dict[str, UUID],
) -> tuple[CitationMention, ...]:
    values: list[CitationMention] = []
    for ordinal, element in enumerate(root.findall(".//xref[@ref-type='bibr']")):
        raw_text = _text(element)
        if not raw_text:
            continue
        targets = element.attrib.get("rid", "").split()
        if not targets:
            targets = [""]
        for target_index, target in enumerate(targets):
            values.append(
                CitationMention(
                    mention_id=_stable_id(
                        document_id, f"mention:{ordinal}:{target_index}:{target}"
                    ),
                    document_id=document_id,
                    raw_text=raw_text,
                    reference_id=reference_targets.get(target),
                    source_anchor=target or None,
                    source_observation_id=observation_id,
                )
            )
    return tuple(values)


def _resource_links(
    root: ET.Element,
    observation_id: UUID,
    artifact_id: UUID,
) -> tuple[ResourceLinkObservation, ...]:
    values: list[ResourceLinkObservation] = []
    candidates = list(root.findall(".//supplementary-material")) + list(
        root.findall(".//self-uri")
    )
    for ordinal, element in enumerate(candidates):
        target = element.attrib.get(_XLINK_HREF) or element.attrib.get("href")
        if not target:
            continue
        values.append(
            ResourceLinkObservation(
                link_id=_stable_id(artifact_id, f"resource:{ordinal}:{target}"),
                observation_id=observation_id,
                target_uri=target,
                relation=ResourceRelation.SUPPLEMENT,
                media_type=element.attrib.get("mimetype"),
                label=_text(element) or None,
                metadata={"native_id": element.attrib.get("id")},
            )
        )
    return tuple(values)


def _article_ids(root: ET.Element) -> dict[str, str]:
    values: dict[str, str] = {}
    for element in root.findall("./front/article-meta/article-id"):
        scheme = element.attrib.get("pub-id-type", "").strip().lower()
        value = _text(element)
        if scheme and value:
            values[scheme] = value
    return values


def _article_identifier(root: ET.Element) -> str | None:
    identifiers = _article_ids(root)
    for scheme in ("pmcid", "pmid", "doi", "publisher-id"):
        if scheme in identifiers:
            return f"{scheme}:{identifiers[scheme]}"
    return None


def _native_ids(elements: Iterable[ET.Element]) -> tuple[str, ...]:
    return tuple(element.attrib["id"] for element in elements if element.attrib.get("id"))


def _strip_element_namespaces(root: ET.Element) -> None:
    """Make JATS element lookup namespace-agnostic without mutating source bytes or attributes."""
    for element in root.iter():
        if isinstance(element.tag, str):
            element.tag = _local_name(element.tag)


def _text(element: ET.Element | None) -> str:
    if element is None:
        return ""
    return " ".join("".join(element.itertext()).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _stable_id(namespace: UUID, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:{namespace}:{key}")
