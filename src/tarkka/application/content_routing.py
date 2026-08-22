from __future__ import annotations

from dataclasses import dataclass

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
        self._manifests = tuple(manifests)

    def route(self, media_type: str | None) -> ContentRouteDecision:
        """Return all parser adapters advertising support for the normalized media type."""
        normalized = _normalize_media_type(media_type)
        if normalized is None:
            return ContentRouteDecision(media_type=None, parser_adapters=())

        candidates = sorted(
            {
                manifest.adapter_name
                for manifest in self._manifests
                if manifest.adapter_kind is AdapterKind.PARSER
                and manifest.supports(Capability.PARSE)
                and normalized in {
                    _normalize_media_type(value) for value in manifest.media_types
                }
            }
        )
        return ContentRouteDecision(
            media_type=normalized,
            parser_adapters=tuple(candidates),
        )


def _normalize_media_type(value: str | None) -> str | None:
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise ValueError("media type must be a non-blank string when provided")
    normalized = value.split(";", 1)[0].strip().lower()
    if "/" not in normalized:
        raise ValueError("media type must contain a type/subtype separator")
    major, minor = normalized.split("/", 1)
    if not major or not minor or any(character.isspace() for character in normalized):
        raise ValueError("media type must be a valid type/subtype value")
    return normalized
