from __future__ import annotations

from dataclasses import dataclass

from tarkka.domain.media_types import normalize_media_type
from tarkka.domain.source_observations import AdapterKind, Capability, CapabilityManifest


@dataclass(frozen=True, slots=True)
class ContentRouteDecision:
    """Deterministic parser candidates for an acquired media type."""

    media_type: str | None
    parser_adapters: tuple[str, ...]

    @property
    def artifact_only(self) -> bool:
        """Return whether no parser currently advertises support for this content."""
        return not self.parser_adapters


class ContentRouter:
    """Route acquired content by capability manifest rather than crawler branching."""

    def __init__(self, manifests: tuple[CapabilityManifest, ...]) -> None:
        routes: dict[str, set[str]] = {}
        for manifest in manifests:
            if not isinstance(manifest, CapabilityManifest):
                raise ValueError("content router manifests must be CapabilityManifest values")
            if manifest.adapter_kind is not AdapterKind.PARSER:
                continue
            if not manifest.supports(Capability.PARSE):
                continue
            for advertised in manifest.media_types:
                normalized = normalize_media_type(advertised)
                if normalized is None:
                    continue
                routes.setdefault(normalized, set()).add(manifest.adapter_name)
        self._routes = {
            media_type: tuple(sorted(names)) for media_type, names in routes.items()
        }

    def route(self, media_type: str | None) -> ContentRouteDecision:
        """Return all parser adapters advertising support for the normalized media type."""
        normalized = normalize_media_type(media_type)
        if normalized is None:
            return ContentRouteDecision(media_type=None, parser_adapters=())
        return ContentRouteDecision(
            media_type=normalized,
            parser_adapters=self._routes.get(normalized, ()),
        )
