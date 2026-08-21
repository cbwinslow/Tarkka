from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
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
from tarkka.ports.parsing import NativeDocumentParseResult

_VOID_TAGS = frozenset(
    {
        "area",
        "base",
        "br",
        "col",
        "embed",
        "hr",
        "img",
        "input",
        "link",
        "meta",
        "source",
        "track",
        "wbr",
    }
)
_IGNORED_TEXT_TAGS = frozenset({"script", "style", "template", "noscript"})
_BLOCK_TAGS = frozenset({"p", "li", "blockquote", "pre", "dd", "dt"})


@dataclass(slots=True)
class _Node:
    tag: str
    attrs: dict[str, str]
    children: list[_Node] = field(default_factory=list)
    content: list[str | _Node] = field(default_factory=list)


class _TreeBuilder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = _Node("document", {})
        self._stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(tag.lower(), {key.lower(): value or "" for key, value in attrs})
        parent = self._stack[-1]
        parent.children.append(node)
        parent.content.append(node)
        if node.tag not in _VOID_TAGS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in _VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        normalized = tag.lower()
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == normalized:
                del self._stack[index:]
                return

    def handle_data(self, data: str) -> None:
        self._stack[-1].content.append(data)


class SemanticHtmlParser:
    """Preserve semantic HTML/XHTML structure before generic reconstruction paths."""

    name = "semantic_html"
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
        media_types=frozenset({"text/html", "application/xhtml+xml"}),
        identifier_schemes=frozenset({"doi"}),
    )

    def supports(self, artifact: Artifact) -> bool:
        if artifact.media_type in self.manifest.media_types:
            return True
        if artifact.original_name is None:
            return False
        return Path(artifact.original_name).suffix.lower() in {".html", ".htm", ".xhtml"}

    def parse(self, artifact: Artifact, path: Path) -> Document:
        return self.parse_native(artifact, path).document

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"unable to read semantic HTML {path}: {exc}") from exc

        builder = _TreeBuilder()
        try:
            builder.feed(source)
            builder.close()
        except (ValueError, AssertionError) as exc:
            raise ValueError(f"unable to parse semantic HTML {path}: {exc}") from exc

        root = builder.root
        document_id = _stable_id(artifact.artifact_id, "semantic-html-document")
        observation_id = _stable_id(artifact.artifact_id, "semantic-html-observation")
        native_metadata = _metadata(root)
        title = native_metadata.get("citation_title") or _first_text(root, "title")
        if not title:
            title = _first_text(root, "h1") or artifact.original_name or "Document"

        sections = _sections(root, document_id, title)
        figures = _figures(root, document_id)
        tables = _tables(root, document_id)
        equations = _equations(root, document_id)
        references, reference_targets = _references(root, document_id, observation_id)
        mentions = _mentions(root, document_id, observation_id, reference_targets)
        links = _resource_links(root, artifact.artifact_id, observation_id)
        metadata: dict[str, object] = dict(native_metadata)
        metadata.update(
            {
                "language": _document_language(root),
                "native_ids": tuple(
                    node.attrs["id"] for node in _walk(root) if node.attrs.get("id")
                ),
                "counts": {
                    "sections": len(sections),
                    "figures": len(figures),
                    "tables": len(tables),
                    "equations": len(equations),
                    "references": len(references),
                    "citation_mentions": len(mentions),
                    "resource_links": len(links),
                },
            }
        )
        observation = SourceObservation(
            observation_id=observation_id,
            source_name=self.name,
            source_version=self.version,
            basis=ObservationBasis.NATIVE,
            media_type=artifact.media_type,
            native_artifact_id=artifact.artifact_id,
            provider_record_id=native_metadata.get("citation_doi"),
            metadata=metadata,
        )
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
        return NativeDocumentParseResult(
            document=document,
            observation=observation,
            references=references,
            mentions=mentions,
            resource_links=links,
        )


def _sections(root: _Node, document_id: UUID, fallback_title: str) -> tuple[Section, ...]:
    content_root = _first_node(root, {"article", "main", "body"}) or root
    events: list[tuple[str, int, str, str | None]] = []
    for node in _walk(content_root):
        if node.tag in _IGNORED_TEXT_TAGS:
            continue
        if len(node.tag) == 2 and node.tag.startswith("h") and node.tag[1].isdigit():
            level = int(node.tag[1])
            if 1 <= level <= 6:
                text = _text(node)
                if text:
                    events.append(("heading", level, text, node.attrs.get("id")))
        elif node.tag in _BLOCK_TAGS and not _has_ancestor_block(content_root, node):
            text = _text(node)
            if text:
                events.append(("block", 0, text, node.attrs.get("id")))

    specs: list[dict[str, object]] = []
    current: dict[str, object] | None = None
    for kind, level, text, native_id in events:
        if kind == "heading":
            current = {
                "title": text,
                "level": level,
                "native_id": native_id,
                "blocks": [],
            }
            specs.append(current)
            continue
        if current is None:
            current = {
                "title": fallback_title,
                "level": 1,
                "native_id": None,
                "blocks": [],
            }
            specs.append(current)
        blocks = current["blocks"]
        assert isinstance(blocks, list)
        blocks.append(text)

    if not specs:
        text = _text(content_root)
        specs.append(
            {
                "title": fallback_title,
                "level": 1,
                "native_id": None,
                "blocks": [text] if text else [],
            }
        )

    sections: list[Section] = []
    parent_stack: list[tuple[int, UUID]] = []
    cursor = 0
    for ordinal, spec in enumerate(specs):
        level_value = spec["level"]
        native_id_value = spec["native_id"]
        blocks_value = spec["blocks"]
        assert isinstance(level_value, int)
        assert native_id_value is None or isinstance(native_id_value, str)
        assert isinstance(blocks_value, list)
        level = level_value
        section_id = _stable_id(
            document_id,
            f"section:{ordinal}:{native_id_value or 'unanchored'}",
        )
        while parent_stack and parent_stack[-1][0] >= level:
            parent_stack.pop()
        parent_id = parent_stack[-1][1] if parent_stack else None
        passages: list[Passage] = []
        for passage_ordinal, block in enumerate(blocks_value):
            assert isinstance(block, str)
            start = cursor
            end = start + len(block)
            passages.append(
                Passage(
                    passage_id=_stable_id(section_id, f"passage:{passage_ordinal}"),
                    document_id=document_id,
                    section_id=section_id,
                    ordinal=passage_ordinal,
                    text=block,
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
                title=str(spec["title"]),
                level=level,
                parent_section_id=parent_id,
                passages=tuple(passages),
            )
        )
        parent_stack.append((level, section_id))
    return tuple(sections)


def _figures(root: _Node, document_id: UUID) -> tuple[Figure, ...]:
    values: list[Figure] = []
    for ordinal, node in enumerate(_nodes(root, "figure")):
        caption_node = next(
            (child for child in _walk(node) if child.tag == "figcaption"), None
        )
        image = next((child for child in _walk(node) if child.tag == "img"), None)
        native_id = node.attrs.get("id")
        values.append(
            Figure(
                figure_id=_stable_id(
                    document_id, f"figure:{ordinal}:{native_id or 'unanchored'}"
                ),
                document_id=document_id,
                ordinal=ordinal,
                label=node.attrs.get("aria-label")
                or (image.attrs.get("alt") if image else None),
                caption=_text(caption_node) or None,
                figure_type="html_figure",
            )
        )
    return tuple(values)


def _tables(root: _Node, document_id: UUID) -> tuple[Table, ...]:
    values: list[Table] = []
    for ordinal, node in enumerate(_nodes(root, "table")):
        rows = [child for child in _walk(node) if child.tag == "tr"]
        columns = max(
            (
                sum(1 for child in row.children if child.tag in {"th", "td"})
                for row in rows
            ),
            default=0,
        )
        caption = next((child for child in node.children if child.tag == "caption"), None)
        native_id = node.attrs.get("id")
        values.append(
            Table(
                table_id=_stable_id(
                    document_id, f"table:{ordinal}:{native_id or 'unanchored'}"
                ),
                document_id=document_id,
                ordinal=ordinal,
                label=node.attrs.get("aria-label"),
                caption=_text(caption) or None,
                row_count=len(rows),
                column_count=columns,
            )
        )
    return tuple(values)


def _equations(root: _Node, document_id: UUID) -> tuple[Equation, ...]:
    values: list[Equation] = []
    for ordinal, node in enumerate(_nodes(root, "math")):
        text = _text(node)
        native_id = node.attrs.get("id")
        values.append(
            Equation(
                equation_id=_stable_id(
                    document_id, f"equation:{ordinal}:{native_id or 'unanchored'}"
                ),
                document_id=document_id,
                ordinal=ordinal,
                label=node.attrs.get("aria-label"),
                source_text=text or None,
            )
        )
    return tuple(values)


def _references(
    root: _Node,
    document_id: UUID,
    observation_id: UUID,
) -> tuple[tuple[BibliographicReference, ...], dict[str, UUID]]:
    candidates = [node for node in _walk(root) if "doc-biblioentry" in _roles(node)]
    values: list[BibliographicReference] = []
    targets: dict[str, UUID] = {}
    for ordinal, node in enumerate(candidates):
        native_id = node.attrs.get("id")
        reference_id = _stable_id(
            document_id,
            f"reference:{ordinal}:{native_id or 'unanchored'}",
        )
        if native_id and native_id not in targets:
            targets[native_id] = reference_id
        identifiers: dict[str, str] = {}
        for link in (item for item in _walk(node) if item.tag == "a"):
            doi = _doi_from_uri(link.attrs.get("href", ""))
            if doi:
                identifiers["doi"] = doi
        raw_text = _text(node)
        if not raw_text:
            continue
        values.append(
            BibliographicReference(
                reference_id=reference_id,
                document_id=document_id,
                ordinal=ordinal,
                raw_text=raw_text,
                identifiers=identifiers,
                source_anchor=native_id,
                source_observation_id=observation_id,
            )
        )
    return tuple(values), targets


def _mentions(
    root: _Node,
    document_id: UUID,
    observation_id: UUID,
    targets: dict[str, UUID],
) -> tuple[CitationMention, ...]:
    values: list[CitationMention] = []
    candidates = [
        node
        for node in _walk(root)
        if node.tag == "a" and "doc-biblioref" in _roles(node)
    ]
    for ordinal, node in enumerate(candidates):
        text = _text(node)
        if not text:
            continue
        anchor = node.attrs.get("href", "").removeprefix("#") or None
        values.append(
            CitationMention(
                mention_id=_stable_id(
                    document_id, f"mention:{ordinal}:{anchor or 'unanchored'}"
                ),
                document_id=document_id,
                raw_text=text,
                reference_id=targets.get(anchor or ""),
                source_anchor=anchor,
                source_observation_id=observation_id,
            )
        )
    return tuple(values)


def _resource_links(
    root: _Node,
    artifact_id: UUID,
    observation_id: UUID,
) -> tuple[ResourceLinkObservation, ...]:
    values: list[ResourceLinkObservation] = []
    for node in _walk(root):
        if node.tag not in {"a", "link"}:
            continue
        href = node.attrs.get("href")
        if not href or href.startswith("#"):
            continue
        rel = set(node.attrs.get("rel", "").lower().split())
        role = node.attrs.get("role", "").lower()
        relation: ResourceRelation | None = None
        if "canonical" in rel:
            relation = ResourceRelation.CANONICAL
        elif "alternate" in rel:
            relation = ResourceRelation.ALTERNATE
        elif (
            "supplement" in rel
            or "supplementary" in rel
            or "doc-supplementary" in role
        ):
            relation = ResourceRelation.SUPPLEMENT
        elif "dataset" in rel:
            relation = ResourceRelation.DATASET
        elif "software" in rel:
            relation = ResourceRelation.SOFTWARE
        elif "download" in node.attrs:
            relation = ResourceRelation.SUPPLEMENT
        if relation is None:
            continue
        ordinal = len(values)
        values.append(
            ResourceLinkObservation(
                link_id=_stable_id(artifact_id, f"html-resource:{ordinal}:{href}"),
                observation_id=observation_id,
                target_uri=href,
                relation=relation,
                media_type=node.attrs.get("type") or None,
                label=_text(node) or None,
                metadata={"rel": tuple(sorted(rel)), "role": role or None},
            )
        )
    return tuple(values)


def _metadata(root: _Node) -> dict[str, str]:
    values: dict[str, str] = {}
    for node in _nodes(root, "meta"):
        key = (
            node.attrs.get("name") or node.attrs.get("property") or ""
        ).strip().lower()
        content = node.attrs.get("content", "").strip()
        if key and content and key not in values:
            values[key] = content
    return values


def _document_language(root: _Node) -> str | None:
    html = next((node for node in _walk(root) if node.tag == "html"), None)
    if html is None:
        return None
    return html.attrs.get("lang") or html.attrs.get("xml:lang") or None


def _roles(node: _Node) -> frozenset[str]:
    return frozenset(node.attrs.get("role", "").lower().split())


def _doi_from_uri(uri: str) -> str | None:
    lower = uri.lower()
    marker = "doi.org/"
    index = lower.find(marker)
    if index < 0:
        return None
    value = uri[index + len(marker) :].strip().rstrip("/.,;)")
    return value.lower() or None


def _first_text(root: _Node, tag: str) -> str:
    node = next((candidate for candidate in _walk(root) if candidate.tag == tag), None)
    return _text(node)


def _first_node(root: _Node, tags: set[str]) -> _Node | None:
    return next((candidate for candidate in _walk(root) if candidate.tag in tags), None)


def _nodes(root: _Node, tag: str) -> tuple[_Node, ...]:
    return tuple(node for node in _walk(root) if node.tag == tag)


def _walk(root: _Node) -> Iterator[_Node]:
    yield root
    for child in root.children:
        yield from _walk(child)


def _text(node: _Node | None) -> str:
    if node is None or node.tag in _IGNORED_TEXT_TAGS:
        return ""
    parts: list[str] = []
    for item in node.content:
        parts.append(item if isinstance(item, str) else _text(item))
    return " ".join("".join(parts).split())


def _has_ancestor_block(root: _Node, target: _Node) -> bool:
    def visit(node: _Node, blocked: bool) -> bool:
        descendant_blocked = blocked or node.tag in _BLOCK_TAGS
        for child in node.children:
            if child is target:
                return descendant_blocked
            if visit(child, descendant_blocked):
                return True
        return False

    return visit(root, False)


def _stable_id(namespace: UUID, key: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"tarkka:{namespace}:{key}")
