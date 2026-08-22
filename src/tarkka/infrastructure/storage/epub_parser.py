from __future__ import annotations

import hashlib
import posixpath
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PurePosixPath
from urllib.parse import unquote, urlsplit, urlunsplit
from uuid import NAMESPACE_URL, UUID, uuid5

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
from tarkka.infrastructure.storage.semantic_html_parser import SemanticHtmlParser
from tarkka.ports.parsing import NativeDocumentParseResult

_EPUB_MEDIA_TYPE = "application/epub+zip"
_XHTML_MEDIA_TYPES = frozenset({"application/xhtml+xml", "text/html"})
_CONTAINER_PATH = "META-INF/container.xml"
_MAX_ENTRIES = 20_000
_MAX_TOTAL_UNCOMPRESSED_BYTES = 1024 * 1024 * 1024
_MAX_MEMBER_BYTES = 128 * 1024 * 1024
_MAX_PACKAGE_BYTES = 16 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _ManifestItem:
    item_id: str
    href: str
    member_path: str
    media_type: str
    properties: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class _SpineItem:
    idref: str
    linear: bool
    properties: tuple[str, ...] = ()


@dataclass(slots=True)
class _Aggregate:
    document_id: UUID
    observation_id: UUID
    sections: list[Section] = field(default_factory=list)
    figures: list[Figure] = field(default_factory=list)
    tables: list[Table] = field(default_factory=list)
    equations: list[Equation] = field(default_factory=list)
    references: list[BibliographicReference] = field(default_factory=list)
    mentions: list[CitationMention] = field(default_factory=list)
    resource_links: list[ResourceLinkObservation] = field(default_factory=list)
    cursor: int = 0


class EpubParser:
    """Preserve EPUB package metadata and linear spine structure."""

    name = "epub"
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
        media_types=frozenset({_EPUB_MEDIA_TYPE}),
    )

    def __init__(self, html_parser: SemanticHtmlParser | None = None) -> None:
        self._html_parser = html_parser or SemanticHtmlParser()

    def supports(self, artifact: Artifact) -> bool:
        if artifact.media_type == _EPUB_MEDIA_TYPE:
            return True
        return bool(
            artifact.original_name
            and Path(artifact.original_name).suffix.lower() == ".epub"
        )

    def parse(self, artifact: Artifact, path: Path) -> Document:
        return self.parse_native(artifact, path).document

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult:
        document_id = _stable_id(artifact.artifact_id, "epub-document")
        observation_id = _stable_id(artifact.artifact_id, "epub-observation")
        aggregate = _Aggregate(document_id=document_id, observation_id=observation_id)

        try:
            with zipfile.ZipFile(path) as archive:
                package_data = _read_package(archive)
                package_path, package, manifest_items, spine_items = package_data
                package_metadata = _package_metadata(package)
                manifest_by_id = {item.item_id: item for item in manifest_items}
                aggregate.resource_links.extend(
                    _package_resource_links(
                        artifact,
                        observation_id,
                        manifest_items,
                        spine_items,
                    )
                )
                parsed_spine = self._parse_spine(
                    artifact,
                    archive,
                    manifest_by_id,
                    spine_items,
                    aggregate,
                )
        except (OSError, zipfile.BadZipFile) as exc:
            raise ValueError(f"unable to read EPUB {path}: {exc}") from exc

        if not parsed_spine:
            raise ValueError("EPUB has no supported linear XHTML spine content")

        title = _first_metadata_value(package_metadata, "titles")
        if title is None:
            title = str(parsed_spine[0]["title"])
        provider_record_id = _package_identifier(package, package_metadata)
        metadata: dict[str, object] = {
            "package_path": package_path,
            "package_version": package.attrib.get("version"),
            "package_attributes": dict(package.attrib),
            "metadata": package_metadata,
            "manifest": tuple(_manifest_metadata(item) for item in manifest_items),
            "spine": tuple(
                {
                    "index": index,
                    "idref": item.idref,
                    "linear": item.linear,
                    "properties": item.properties,
                }
                for index, item in enumerate(spine_items)
            ),
            "parsed_spine": tuple(parsed_spine),
            "counts": _aggregate_counts(aggregate),
        }
        observation = SourceObservation(
            observation_id=observation_id,
            source_name=self.name,
            source_version=self.version,
            basis=ObservationBasis.NATIVE,
            media_type=_EPUB_MEDIA_TYPE,
            native_artifact_id=artifact.artifact_id,
            provider_record_id=provider_record_id,
            metadata=metadata,
        )
        document = Document(
            document_id=document_id,
            artifact_id=artifact.artifact_id,
            title=title,
            parser_name=self.name,
            parser_version=self.version,
            sections=tuple(aggregate.sections),
            figures=tuple(aggregate.figures),
            tables=tuple(aggregate.tables),
            equations=tuple(aggregate.equations),
        )
        return NativeDocumentParseResult(
            document=document,
            observation=observation,
            references=tuple(aggregate.references),
            mentions=tuple(aggregate.mentions),
            resource_links=_deduplicate_links(aggregate.resource_links),
        )

    def _parse_spine(
        self,
        artifact: Artifact,
        archive: zipfile.ZipFile,
        manifest_by_id: dict[str, _ManifestItem],
        spine_items: tuple[_SpineItem, ...],
        aggregate: _Aggregate,
    ) -> list[dict[str, object]]:
        parsed_spine: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory(prefix="tarkka-epub-") as temp_dir:
            temp_root = Path(temp_dir)
            for spine_index, spine in enumerate(spine_items):
                if not spine.linear:
                    continue
                item = manifest_by_id[spine.idref]
                if item.media_type not in _XHTML_MEDIA_TYPES:
                    raise ValueError(
                        "unsupported linear EPUB spine media type "
                        f"{item.media_type!r} for {item.member_path!r}"
                    )
                source_bytes = _read_member(
                    archive,
                    item.member_path,
                    _MAX_MEMBER_BYTES,
                )
                source_text = _decode_xhtml(source_bytes, item.member_path)
                temp_path = temp_root / f"spine-{spine_index:05d}.xhtml"
                temp_path.write_text(source_text, encoding="utf-8")
                child = self._html_parser.parse_native(
                    _spine_artifact(artifact, item, source_bytes),
                    temp_path,
                )
                _append_spine_result(
                    aggregate,
                    child,
                    spine_index=spine_index,
                    member_path=item.member_path,
                )
                parsed_spine.append(
                    {
                        "index": spine_index,
                        "idref": spine.idref,
                        "member_path": item.member_path,
                        "media_type": item.media_type,
                        "title": child.document.title,
                    }
                )
        return parsed_spine


def _append_spine_result(
    aggregate: _Aggregate,
    result: NativeDocumentParseResult,
    *,
    spine_index: int,
    member_path: str,
) -> None:
    chapter_offset = aggregate.cursor
    section_map: dict[UUID, UUID] = {}
    passage_map: dict[UUID, UUID] = {}

    for source_section in result.document.sections:
        section_id = _stable_id(
            aggregate.document_id,
            f"spine:{spine_index}:{member_path}:section:{source_section.ordinal}",
        )
        section_map[source_section.section_id] = section_id
        passages: list[Passage] = []
        for source_passage in source_section.passages:
            passage_id = _stable_id(section_id, f"passage:{source_passage.ordinal}")
            passage_map[source_passage.passage_id] = passage_id
            start = aggregate.cursor
            end = start + len(source_passage.text)
            passages.append(
                Passage(
                    passage_id=passage_id,
                    document_id=aggregate.document_id,
                    section_id=section_id,
                    ordinal=source_passage.ordinal,
                    text=source_passage.text,
                    char_start=start,
                    char_end=end,
                )
            )
            aggregate.cursor = end + 1

        parent_id = (
            section_map.get(source_section.parent_section_id)
            if source_section.parent_section_id is not None
            else None
        )
        aggregate.sections.append(
            Section(
                section_id=section_id,
                document_id=aggregate.document_id,
                ordinal=len(aggregate.sections),
                title=source_section.title,
                level=source_section.level,
                parent_section_id=parent_id,
                passages=tuple(passages),
            )
        )

    _append_source_artifacts(aggregate, result, spine_index, member_path)
    reference_map = _append_references(aggregate, result, spine_index, member_path)
    _append_mentions(
        aggregate,
        result,
        spine_index,
        member_path,
        chapter_offset,
        section_map,
        passage_map,
        reference_map,
    )
    _append_resource_links(aggregate, result, spine_index, member_path)


def _append_source_artifacts(
    aggregate: _Aggregate,
    result: NativeDocumentParseResult,
    spine_index: int,
    member_path: str,
) -> None:
    for item in result.document.figures:
        aggregate.figures.append(
            Figure(
                figure_id=_stable_id(
                    aggregate.document_id,
                    f"spine:{spine_index}:{member_path}:figure:{item.ordinal}",
                ),
                document_id=aggregate.document_id,
                ordinal=len(aggregate.figures),
                page_number=item.page_number,
                label=item.label,
                caption=item.caption,
                figure_type=item.figure_type,
            )
        )
    for item in result.document.tables:
        aggregate.tables.append(
            Table(
                table_id=_stable_id(
                    aggregate.document_id,
                    f"spine:{spine_index}:{member_path}:table:{item.ordinal}",
                ),
                document_id=aggregate.document_id,
                ordinal=len(aggregate.tables),
                page_number=item.page_number,
                label=item.label,
                caption=item.caption,
                row_count=item.row_count,
                column_count=item.column_count,
            )
        )
    for item in result.document.equations:
        aggregate.equations.append(
            Equation(
                equation_id=_stable_id(
                    aggregate.document_id,
                    f"spine:{spine_index}:{member_path}:equation:{item.ordinal}",
                ),
                document_id=aggregate.document_id,
                ordinal=len(aggregate.equations),
                page_number=item.page_number,
                label=item.label,
                source_text=item.source_text,
            )
        )


def _append_references(
    aggregate: _Aggregate,
    result: NativeDocumentParseResult,
    spine_index: int,
    member_path: str,
) -> dict[UUID, UUID]:
    reference_map: dict[UUID, UUID] = {}
    for item in result.references:
        reference_id = _stable_id(
            aggregate.document_id,
            f"spine:{spine_index}:{member_path}:reference:{item.ordinal}",
        )
        reference_map[item.reference_id] = reference_id
        aggregate.references.append(
            BibliographicReference(
                reference_id=reference_id,
                document_id=aggregate.document_id,
                ordinal=len(aggregate.references),
                raw_text=item.raw_text,
                identifiers=dict(item.identifiers),
                title=item.title,
                authors=item.authors,
                publication_year=item.publication_year,
                source_anchor=_prefixed_anchor(member_path, item.source_anchor),
                source_observation_id=aggregate.observation_id,
            )
        )
    return reference_map


def _append_mentions(
    aggregate: _Aggregate,
    result: NativeDocumentParseResult,
    spine_index: int,
    member_path: str,
    chapter_offset: int,
    section_map: dict[UUID, UUID],
    passage_map: dict[UUID, UUID],
    reference_map: dict[UUID, UUID],
) -> None:
    for item in result.mentions:
        aggregate.mentions.append(
            CitationMention(
                mention_id=_stable_id(
                    aggregate.document_id,
                    f"spine:{spine_index}:{member_path}:mention:{len(aggregate.mentions)}",
                ),
                document_id=aggregate.document_id,
                raw_text=item.raw_text,
                reference_id=(
                    reference_map.get(item.reference_id)
                    if item.reference_id is not None
                    else None
                ),
                section_id=(
                    section_map.get(item.section_id)
                    if item.section_id is not None
                    else None
                ),
                passage_id=(
                    passage_map.get(item.passage_id)
                    if item.passage_id is not None
                    else None
                ),
                char_start=(
                    chapter_offset + item.char_start
                    if item.char_start is not None
                    else None
                ),
                char_end=(
                    chapter_offset + item.char_end
                    if item.char_end is not None
                    else None
                ),
                source_anchor=_prefixed_anchor(member_path, item.source_anchor),
                source_observation_id=aggregate.observation_id,
            )
        )


def _append_resource_links(
    aggregate: _Aggregate,
    result: NativeDocumentParseResult,
    spine_index: int,
    member_path: str,
) -> None:
    for item in result.resource_links:
        aggregate.resource_links.append(
            ResourceLinkObservation(
                link_id=_stable_id(
                    aggregate.observation_id,
                    f"spine:{spine_index}:{member_path}:link:{item.link_id}",
                ),
                observation_id=aggregate.observation_id,
                target_uri=_resolve_resource_target(member_path, item.target_uri),
                relation=item.relation,
                media_type=item.media_type,
                label=item.label,
                metadata={**dict(item.metadata), "spine_member": member_path},
            )
        )


def _read_package(
    archive: zipfile.ZipFile,
) -> tuple[
    str,
    ET.Element,
    tuple[_ManifestItem, ...],
    tuple[_SpineItem, ...],
]:
    _validate_archive(archive)
    _validate_mimetype(archive)
    container = _parse_xml(
        _read_member(archive, _CONTAINER_PATH, _MAX_PACKAGE_BYTES),
        label="EPUB container",
    )
    package_path = _package_path(container)
    package = _parse_xml(
        _read_member(archive, package_path, _MAX_PACKAGE_BYTES),
        label="EPUB package document",
    )
    package_dir = PurePosixPath(package_path).parent
    manifest_items = _manifest_items(package, package_dir, archive)
    manifest_by_id = {item.item_id: item for item in manifest_items}
    spine_items = _spine_items(package, manifest_by_id)
    return package_path, package, manifest_items, spine_items


def _validate_archive(archive: zipfile.ZipFile) -> None:
    infos = archive.infolist()
    if not infos:
        raise ValueError("EPUB archive is empty")
    if len(infos) > _MAX_ENTRIES:
        raise ValueError(f"EPUB contains too many archive entries: {len(infos)}")
    total = 0
    for info in infos:
        _validate_member_name(info.filename)
        if info.flag_bits & 0x1:
            raise ValueError(f"encrypted EPUB member is unsupported: {info.filename!r}")
        if info.file_size < 0:
            raise ValueError(f"invalid EPUB member size: {info.filename!r}")
        total += info.file_size
        if total > _MAX_TOTAL_UNCOMPRESSED_BYTES:
            raise ValueError("EPUB exceeds the maximum uncompressed size")


def _validate_mimetype(archive: zipfile.ZipFile) -> None:
    first = archive.infolist()[0]
    if first.filename != "mimetype" or first.compress_type != zipfile.ZIP_STORED:
        raise ValueError("EPUB mimetype entry must be first and uncompressed")
    try:
        value = _read_member(archive, "mimetype", 1024).decode("ascii", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("EPUB mimetype must be ASCII") from exc
    if value != _EPUB_MEDIA_TYPE:
        raise ValueError(f"invalid EPUB mimetype value: {value!r}")


def _validate_member_name(name: str) -> None:
    if not name or "\\" in name or name.startswith("/"):
        raise ValueError(f"unsafe EPUB member path: {name!r}")
    normalized = posixpath.normpath(name)
    if normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"unsafe EPUB member path: {name!r}")


def _read_member(archive: zipfile.ZipFile, name: str, max_bytes: int) -> bytes:
    _validate_member_name(name)
    try:
        info = archive.getinfo(name)
    except KeyError as exc:
        raise ValueError(f"missing required EPUB member: {name!r}") from exc
    if info.file_size > max_bytes:
        raise ValueError(f"EPUB member exceeds size limit: {name!r}")
    data = archive.read(info)
    if len(data) > max_bytes:
        raise ValueError(f"EPUB member exceeds size limit after decompression: {name!r}")
    return data


def _parse_xml(data: bytes, *, label: str) -> ET.Element:
    try:
        return ET.fromstring(data)
    except ET.ParseError as exc:
        raise ValueError(f"invalid {label}: {exc}") from exc


def _package_path(container: ET.Element) -> str:
    rootfiles = [
        element
        for element in container.iter()
        if _local_name(element.tag) == "rootfile"
    ]
    for rootfile in rootfiles:
        media_type = rootfile.attrib.get("media-type", "")
        full_path = rootfile.attrib.get("full-path", "").strip()
        if full_path and media_type == "application/oebps-package+xml":
            return _normalize_package_member(full_path)
    if rootfiles:
        full_path = rootfiles[0].attrib.get("full-path", "").strip()
        if full_path:
            return _normalize_package_member(full_path)
    raise ValueError("EPUB container does not identify a package document")


def _normalize_package_member(path: str) -> str:
    decoded = unquote(path)
    _validate_member_name(decoded)
    return posixpath.normpath(decoded)


def _manifest_items(
    package: ET.Element,
    package_dir: PurePosixPath,
    archive: zipfile.ZipFile,
) -> tuple[_ManifestItem, ...]:
    manifest = _first_child(package, "manifest")
    if manifest is None:
        raise ValueError("EPUB package is missing manifest")
    values: list[_ManifestItem] = []
    seen_ids: set[str] = set()
    for element in manifest:
        if _local_name(element.tag) != "item":
            continue
        item_id = element.attrib.get("id", "").strip()
        href = element.attrib.get("href", "").strip()
        media_type = element.attrib.get("media-type", "").strip()
        if not item_id or not href or not media_type:
            raise ValueError("EPUB manifest items require id, href, and media-type")
        if item_id in seen_ids:
            raise ValueError(f"duplicate EPUB manifest id: {item_id!r}")
        member_path = _resolve_member_path(package_dir, href)
        try:
            archive.getinfo(member_path)
        except KeyError as exc:
            raise ValueError(
                f"EPUB manifest member is missing from archive: {member_path!r}"
            ) from exc
        seen_ids.add(item_id)
        values.append(
            _ManifestItem(
                item_id=item_id,
                href=href,
                member_path=member_path,
                media_type=media_type,
                properties=tuple(element.attrib.get("properties", "").split()),
            )
        )
    if not values:
        raise ValueError("EPUB manifest is empty")
    return tuple(values)


def _spine_items(
    package: ET.Element,
    manifest_by_id: dict[str, _ManifestItem],
) -> tuple[_SpineItem, ...]:
    spine = _first_child(package, "spine")
    if spine is None:
        raise ValueError("EPUB package is missing spine")
    values: list[_SpineItem] = []
    for element in spine:
        if _local_name(element.tag) != "itemref":
            continue
        idref = element.attrib.get("idref", "").strip()
        if not idref:
            raise ValueError("EPUB spine itemref is missing idref")
        if idref not in manifest_by_id:
            raise ValueError(f"EPUB spine references unknown manifest id: {idref!r}")
        linear_value = element.attrib.get("linear", "yes").strip().lower()
        if linear_value not in {"yes", "no"}:
            raise ValueError(f"invalid EPUB spine linear value: {linear_value!r}")
        values.append(
            _SpineItem(
                idref=idref,
                linear=linear_value != "no",
                properties=tuple(element.attrib.get("properties", "").split()),
            )
        )
    if not values:
        raise ValueError("EPUB spine is empty")
    return tuple(values)


def _package_metadata(package: ET.Element) -> dict[str, object]:
    metadata = _first_child(package, "metadata")
    if metadata is None:
        return {}
    names = (
        "title",
        "language",
        "identifier",
        "creator",
        "publisher",
        "date",
        "rights",
        "subject",
        "description",
    )
    values: dict[str, object] = {}
    for name in names:
        matches = tuple(
            text
            for element in metadata
            if _local_name(element.tag) == name
            if (text := _element_text(element))
        )
        if matches:
            values[f"{name}s"] = matches
    modified = tuple(
        text
        for element in metadata
        if _local_name(element.tag) == "meta"
        if element.attrib.get("property") == "dcterms:modified"
        if (text := _element_text(element))
    )
    if modified:
        values["modified"] = modified
    return values


def _package_identifier(package: ET.Element, metadata: dict[str, object]) -> str | None:
    metadata_node = _first_child(package, "metadata")
    unique_id = package.attrib.get("unique-identifier")
    if metadata_node is not None and unique_id:
        for element in metadata_node:
            if element.attrib.get("id") == unique_id:
                text = _element_text(element)
                if text:
                    return text
    return _first_metadata_value(metadata, "identifiers")


def _first_metadata_value(metadata: dict[str, object], key: str) -> str | None:
    raw = metadata.get(key)
    if isinstance(raw, tuple) and raw and isinstance(raw[0], str):
        return raw[0]
    return None


def _manifest_metadata(item: _ManifestItem) -> dict[str, object]:
    return {
        "id": item.item_id,
        "href": item.href,
        "member_path": item.member_path,
        "media_type": item.media_type,
        "properties": item.properties,
    }


def _package_resource_links(
    artifact: Artifact,
    observation_id: UUID,
    items: tuple[_ManifestItem, ...],
    spine: tuple[_SpineItem, ...],
) -> tuple[ResourceLinkObservation, ...]:
    spine_ids = {item.idref for item in spine}
    values: list[ResourceLinkObservation] = []
    for item in items:
        in_spine = item.item_id in spine_ids
        relation = ResourceRelation.FULL_TEXT if in_spine else ResourceRelation.RELATED
        values.append(
            ResourceLinkObservation(
                link_id=_stable_id(
                    artifact.artifact_id,
                    f"epub-manifest-resource:{item.item_id}:{item.member_path}",
                ),
                observation_id=observation_id,
                target_uri=item.member_path,
                relation=relation,
                media_type=item.media_type,
                label=item.item_id,
                metadata={
                    "href": item.href,
                    "properties": item.properties,
                    "in_spine": in_spine,
                },
            )
        )
    return tuple(values)


def _resolve_member_path(package_dir: PurePosixPath, href: str) -> str:
    parts = urlsplit(href)
    if parts.scheme or parts.netloc:
        raise ValueError(f"EPUB manifest href must be package-relative: {href!r}")
    decoded = unquote(parts.path)
    if not decoded:
        raise ValueError(f"EPUB manifest href has no path: {href!r}")
    combined = posixpath.normpath(posixpath.join(package_dir.as_posix(), decoded))
    _validate_member_name(combined)
    return combined


def _resolve_resource_target(member_path: str, target: str) -> str:
    parts = urlsplit(target)
    if parts.scheme or parts.netloc:
        return target
    decoded = unquote(parts.path)
    if not decoded:
        return target
    base = PurePosixPath(member_path).parent
    resolved = _resolve_member_path(base, decoded)
    return urlunsplit(("", "", resolved, parts.query, parts.fragment))


def _decode_xhtml(data: bytes, member_path: str) -> str:
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError as exc:
        raise ValueError(f"EPUB XHTML member is not UTF-8: {member_path!r}") from exc


def _spine_artifact(
    package_artifact: Artifact,
    item: _ManifestItem,
    source_bytes: bytes,
) -> Artifact:
    digest = hashlib.sha256(source_bytes).hexdigest()
    base_uri = package_artifact.source_uri
    if base_uri is None:
        base_uri = f"urn:tarkka:artifact:{package_artifact.artifact_id}"
    return Artifact(
        artifact_id=_stable_id(
            package_artifact.artifact_id,
            f"epub-member:{item.member_path}:{digest}",
        ),
        sha256=digest,
        size_bytes=len(source_bytes),
        media_type=item.media_type,
        storage_key=PurePosixPath("epub", package_artifact.sha256, item.member_path),
        original_name=item.member_path,
        source_uri=f"{base_uri}#epub-member={item.member_path}",
    )


def _aggregate_counts(aggregate: _Aggregate) -> dict[str, int]:
    return {
        "sections": len(aggregate.sections),
        "figures": len(aggregate.figures),
        "tables": len(aggregate.tables),
        "equations": len(aggregate.equations),
        "references": len(aggregate.references),
        "citation_mentions": len(aggregate.mentions),
        "resource_links": len(aggregate.resource_links),
    }


def _deduplicate_links(
    links: list[ResourceLinkObservation],
) -> tuple[ResourceLinkObservation, ...]:
    seen: set[tuple[str, ResourceRelation, str | None, str | None]] = set()
    values: list[ResourceLinkObservation] = []
    for link in links:
        key = (link.target_uri, link.relation, link.media_type, link.label)
        if key in seen:
            continue
        seen.add(key)
        values.append(link)
    return tuple(values)


def _prefixed_anchor(member_path: str, anchor: str | None) -> str | None:
    if anchor is None:
        return None
    return f"{member_path}::{anchor}"


def _first_child(element: ET.Element, name: str) -> ET.Element | None:
    return next((child for child in element if _local_name(child.tag) == name), None)


def _element_text(element: ET.Element) -> str:
    return " ".join("".join(element.itertext()).split())


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _stable_id(namespace: UUID, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:{namespace}:{key}")
