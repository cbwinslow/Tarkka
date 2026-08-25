"""Native-preserving parser for standalone LaTeX research source files.

This adapter deliberately recognizes a bounded structural subset; it never executes TeX,
expands arbitrary macros, or follows ``\\input``/``\\include`` files.  Those operations belong
to a future, explicitly bounded source-bundle acquisition workflow.
"""

from __future__ import annotations

import mimetypes
import re
from pathlib import Path
from uuid import UUID

from tarkka.domain.citations import BibliographicReference, CitationMention
from tarkka.domain.models import Artifact, Document
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
from tarkka.infrastructure.storage.markdown_normalizer import document_from_markdown
from tarkka.infrastructure.storage.parser_identity import parser_stable_id
from tarkka.ports.parsing import NativeDocumentParseResult

_ENVIRONMENT = re.compile(r"\\begin\{(?P<name>[^}]+)\}(?P<body>.*?)\\end\{(?P=name)\}", re.DOTALL)
_BIB_ITEM = re.compile(
    r"\\bibitem(?:\[[^\]]*\])?\{(?P<key>[^}]+)\}(?P<body>.*?)(?=\\bibitem|\\end\{thebibliography\}|\Z)",
    re.DOTALL,
)
_CITATION = re.compile(
    r"\\(?:cite|citep|citet|citealp|citeauthor)\*?(?:\[[^\]]*\])*\{(?P<keys>[^}]+)\}"
)
_SECTION = re.compile(r"\\(?P<kind>section|subsection|subsubsection)\*?\{(?P<title>[^}]+)\}")
_COMMAND_WITH_ARGUMENT = re.compile(
    r"\\(?:emph|textbf|textit|textrm|url|href)\*?(?:\[[^\]]*\])?\{(?P<value>[^}]*)\}"
)
_INCLUDE_GRAPHICS = re.compile(r"\\includegraphics(?:\[[^\]]*\])?\{(?P<path>[^}]+)\}")
_LABEL = re.compile(r"\\label\{(?P<label>[^}]+)\}")
_TITLE = re.compile(r"\\title\{(?P<title>[^}]+)\}")
_DOCUMENT_CLASS = re.compile(r"\\documentclass(?:\[[^\]]*\])?\{(?P<class>[^}]+)\}")


class LatexParser:
    """Preserve source-native LaTeX structure without treating rendered output as native."""

    name = "latex"
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
                Capability.DOCUMENT_STRUCTURE,
                Capability.BIBLIOGRAPHY,
                Capability.INLINE_CITATIONS,
                Capability.FIGURES,
                Capability.TABLES,
                Capability.EQUATIONS,
                Capability.LINK_DISCOVERY,
            }
        ),
        media_types=frozenset({"text/x-tex", "application/x-tex"}),
    )

    def supports(self, artifact: Artifact) -> bool:
        return artifact.media_type in self.manifest.media_types or (
            artifact.original_name is not None
            and Path(artifact.original_name).suffix.lower() in {".tex", ".latex"}
        )

    def parse(self, artifact: Artifact, path: Path) -> Document:
        return self.parse_native(artifact, path).document

    def parse_native(self, artifact: Artifact, path: Path) -> NativeDocumentParseResult:
        try:
            source = path.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            raise ValueError(f"unable to read LaTeX source {path}: {exc}") from exc
        source = _strip_comments(source)
        document_id = parser_stable_id(artifact.artifact_id, "latex-document")
        observation_id = parser_stable_id(artifact.artifact_id, "latex-observation")
        title = _first_group(_TITLE, source) or artifact.original_name or "Document"
        normalized = _normalized_text(source)
        document = document_from_markdown(
            artifact=artifact,
            text=normalized,
            parser_name=self.name,
            parser_version=self.version,
            title=_plain_text(title),
            document_id=document_id,
        )
        references = _references(source, document_id, observation_id)
        mentions = _mentions(normalized, document, references, observation_id)
        figures = _figures(source, document_id)
        tables = _tables(source, document_id)
        equations = _equations(source, document_id)
        document = Document(
            document_id=document.document_id,
            artifact_id=document.artifact_id,
            title=document.title,
            parser_name=document.parser_name,
            parser_version=document.parser_version,
            sections=document.sections,
            figures=figures,
            tables=tables,
            equations=equations,
        )
        links = _resource_links(source, observation_id)
        labels = tuple(match.group("label").strip() for match in _LABEL.finditer(source))
        observation = SourceObservation(
            observation_id=observation_id,
            source_name=self.name,
            source_version=self.version,
            basis=ObservationBasis.NATIVE,
            media_type=artifact.media_type,
            native_artifact_id=artifact.artifact_id,
            metadata={
                "document_class": _first_group(_DOCUMENT_CLASS, source),
                "native_labels": labels,
                "bibliography_keys": tuple(reference.source_anchor for reference in references),
                "counts": {
                    "sections": len(document.sections),
                    "figures": len(figures),
                    "tables": len(tables),
                    "equations": len(equations),
                    "references": len(references),
                    "citation_mentions": len(mentions),
                    "resource_links": len(links),
                },
            },
        )
        return NativeDocumentParseResult(
            document=document,
            observation=observation,
            references=references,
            mentions=mentions,
            resource_links=links,
        )


def _strip_comments(source: str) -> str:
    return "\n".join(re.split(r"(?<!\\)%", line, maxsplit=1)[0] for line in source.splitlines())


def _normalized_text(source: str) -> str:
    body = source.split(r"\begin{document}", 1)[-1].split(r"\end{document}", 1)[0]
    body = _CITATION.sub(
        lambda match: " ".join(
            f"[{key.strip()}]" for key in match.group("keys").split(",") if key.strip()
        ),
        body,
    )
    body = _SECTION.sub(
        lambda match: (
            "#" * {"section": 1, "subsection": 2, "subsubsection": 3}[match.group("kind")]
            + f" {_plain_text(match.group('title'))}\n"
        ),
        body,
    )
    body = _ENVIRONMENT.sub(
        lambda match: (
            "\n"
            if match.group("name") in {"figure", "table", "equation", "align", "thebibliography"}
            else match.group("body")
        ),
        body,
    )
    body = _INCLUDE_GRAPHICS.sub("", body)
    body = _LABEL.sub("", body)
    body = _COMMAND_WITH_ARGUMENT.sub(lambda match: _plain_text(match.group("value")), body)
    body = re.sub(r"\\(?:ref|pageref|cite)\*?(?:\[[^\]]*\])?\{[^}]*\}", "", body)
    body = re.sub(r"\\[A-Za-z@]+\*?", "", body)
    body = body.replace("{", "").replace("}", "")
    return re.sub(r"\n{3,}", "\n\n", body).strip()


def _references(
    source: str, document_id: UUID, observation_id: UUID
) -> tuple[BibliographicReference, ...]:
    return tuple(
        BibliographicReference(
            reference_id=parser_stable_id(document_id, f"reference:{match.group('key').strip()}"),
            document_id=document_id,
            ordinal=ordinal,
            raw_text=_plain_text(match.group("body")),
            source_anchor=match.group("key").strip(),
            source_observation_id=observation_id,
        )
        for ordinal, match in enumerate(_BIB_ITEM.finditer(source))
        if _plain_text(match.group("body"))
    )


def _mentions(
    normalized: str,
    document: Document,
    references: tuple[BibliographicReference, ...],
    observation_id: UUID,
) -> tuple[CitationMention, ...]:
    by_key = {reference.source_anchor: reference for reference in references}
    mentions: list[CitationMention] = []
    for ordinal, match in enumerate(re.finditer(r"\[(?P<key>[^\]]+)\]", normalized)):
        key = match.group("key")
        reference = by_key.get(key)
        if reference is None:
            continue
        for section in document.sections:
            for passage in section.passages:
                index = passage.text.find(match.group(0))
                if index >= 0:
                    start = passage.char_start + index
                    mentions.append(
                        CitationMention(
                            mention_id=parser_stable_id(
                                document.document_id, f"mention:{ordinal}:{key}"
                            ),
                            document_id=document.document_id,
                            raw_text=match.group(0),
                            reference_id=reference.reference_id,
                            section_id=section.section_id,
                            passage_id=passage.passage_id,
                            char_start=start,
                            char_end=start + len(match.group(0)),
                            source_anchor=key,
                            source_observation_id=observation_id,
                        )
                    )
                    break
            else:
                continue
            break
    return tuple(mentions)


def _figures(source: str, document_id: UUID) -> tuple[Figure, ...]:
    return tuple(
        Figure(
            figure_id=parser_stable_id(
                document_id, f"figure:{ordinal}:{_label(body) or 'unlabeled'}"
            ),
            document_id=document_id,
            ordinal=ordinal,
            label=_label(body),
            caption=_caption(body),
            figure_type="latex_figure",
        )
        for ordinal, body in enumerate(_environment_bodies(source, "figure"))
    )


def _tables(source: str, document_id: UUID) -> tuple[Table, ...]:
    return tuple(
        Table(
            table_id=parser_stable_id(
                document_id, f"table:{ordinal}:{_label(body) or 'unlabeled'}"
            ),
            document_id=document_id,
            ordinal=ordinal,
            label=_label(body),
            caption=_caption(body),
            row_count=body.count(r"\\") or None,
            column_count=(
                max((line.count("&") + 1 for line in body.splitlines() if "&" in line), default=0)
                or None
            ),
        )
        for ordinal, body in enumerate(_environment_bodies(source, "table"))
    )


def _equations(source: str, document_id: UUID) -> tuple[Equation, ...]:
    bodies = [*(_environment_bodies(source, "equation")), *(_environment_bodies(source, "align"))]
    return tuple(
        Equation(
            equation_id=parser_stable_id(
                document_id, f"equation:{ordinal}:{_label(body) or 'unlabeled'}"
            ),
            document_id=document_id,
            ordinal=ordinal,
            label=_label(body),
            source_text=_plain_text(_LABEL.sub("", body)),
        )
        for ordinal, body in enumerate(bodies)
        if _plain_text(_LABEL.sub("", body))
    )


def _resource_links(source: str, observation_id: UUID) -> tuple[ResourceLinkObservation, ...]:
    return tuple(
        ResourceLinkObservation(
            link_id=parser_stable_id(
                observation_id, f"graphic:{ordinal}:{match.group('path').strip()}"
            ),
            observation_id=observation_id,
            target_uri=match.group("path").strip(),
            relation=ResourceRelation.RELATED,
            media_type=mimetypes.guess_type(match.group("path").strip())[0],
            label=None,
            metadata={"source_command": "includegraphics"},
        )
        for ordinal, match in enumerate(_INCLUDE_GRAPHICS.finditer(source))
    )


def _environment_bodies(source: str, name: str) -> tuple[str, ...]:
    pattern = re.compile(
        rf"\\begin\{{{re.escape(name)}\}}(?P<body>.*?)\\end\{{{re.escape(name)}\}}",
        re.DOTALL,
    )
    return tuple(match.group("body") for match in pattern.finditer(source))


def _caption(source: str) -> str | None:
    match = re.search(r"\\caption\{(?P<caption>[^}]+)\}", source)
    return _plain_text(match.group("caption")) if match else None


def _label(source: str) -> str | None:
    match = _LABEL.search(source)
    return match.group("label").strip() if match else None


def _plain_text(value: str) -> str:
    return " ".join(re.sub(r"\\[A-Za-z@]+\*?", "", value).replace("{", "").replace("}", "").split())


def _first_group(pattern: re.Pattern[str], source: str) -> str | None:
    match = pattern.search(source)
    return match.group(1).strip() if match else None
