"""Deterministic Markdown renderer for normalized-section compositions."""

from __future__ import annotations

from tarkka.domain.compositions import CompositionFormat, CompositionManifest
from tarkka.domain.path_safety import portable_filename_component
from tarkka.ports.compositions import RenderedComposition, ResolvedCompositionSection


class MarkdownCompositionExporter:
    """Render ordered normalized Sections with source locators and basis labels."""

    @property
    def format(self) -> CompositionFormat:
        return CompositionFormat.MARKDOWN

    @property
    def name(self) -> str:
        return "tarkka-markdown"

    @property
    def version(self) -> str:
        return "1"

    def render(
        self,
        manifest: CompositionManifest,
        sections: tuple[ResolvedCompositionSection, ...],
    ) -> RenderedComposition:
        if len(sections) != len(manifest.components):
            raise ValueError("composition renderer requires every manifest component")
        lines = [f"# {manifest.title}", ""]
        for position, section in enumerate(sections, start=1):
            reference = section.reference
            lines.extend(
                (
                    f"## {position}. {section.title}" if section.title else f"## {position}",
                    "",
                    (
                        "Source: "
                        f"artifact sha256:{reference.artifact_sha256}; "
                        f"document:{reference.document_id}; section:{reference.section_id}; "
                        f"basis:{reference.basis}; parser:{reference.parser_name}@"
                        f"{reference.parser_version}."
                    ),
                    "",
                    section.text,
                    "",
                )
            )
        return RenderedComposition(
            data=("\n".join(lines)).encode("utf-8"),
            media_type="text/markdown",
            filename=portable_filename_component(f"{manifest.title}.md"),
        )
