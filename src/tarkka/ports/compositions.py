"""Replaceable deterministic renderers for derived composition exports."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from tarkka.domain.compositions import (
    CompositionFormat,
    CompositionManifest,
    CompositionSectionReference,
)
from tarkka.domain.path_safety import is_safe_filename_component


@dataclass(frozen=True, slots=True)
class ResolvedCompositionSection:
    """One manifest component expanded from its pinned normalized Document version."""

    reference: CompositionSectionReference
    ordinal: int
    title: str
    text: str

    def __post_init__(self) -> None:
        if not isinstance(self.ordinal, int) or isinstance(self.ordinal, bool) or self.ordinal < 0:
            raise ValueError("resolved composition section ordinal must be non-negative")
        if not isinstance(self.title, str):
            raise ValueError("resolved composition section title must be a string")
        if not isinstance(self.text, str):
            raise ValueError("resolved composition section text must be a string")


@dataclass(frozen=True, slots=True)
class RenderedComposition:
    """Exact renderer result before the application service records its digest receipt."""

    data: bytes
    media_type: str
    filename: str

    def __post_init__(self) -> None:
        if not isinstance(self.data, bytes):
            raise ValueError("rendered composition data must be bytes")
        if not isinstance(self.media_type, str) or not self.media_type.strip():
            raise ValueError("rendered composition media_type must be non-blank")
        if not is_safe_filename_component(self.filename):
            raise ValueError("rendered composition filename must be safe")


class CompositionExporter(Protocol):
    """Render a pinned composition without creating or changing its source records."""

    @property
    def format(self) -> CompositionFormat: ...

    @property
    def name(self) -> str: ...

    @property
    def version(self) -> str: ...

    def render(
        self,
        manifest: CompositionManifest,
        sections: tuple[ResolvedCompositionSection, ...],
    ) -> RenderedComposition: ...
