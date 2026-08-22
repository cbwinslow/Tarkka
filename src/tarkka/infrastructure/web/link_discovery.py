from __future__ import annotations

from dataclasses import dataclass, field
from html.parser import HTMLParser
from urllib.parse import urljoin, urlsplit
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)

_LINK_TAGS = frozenset({"a", "area", "link"})


@dataclass(slots=True)
class _PendingAnchor:
    attrs: dict[str, str]
    line: int
    offset: int
    text_parts: list[str] = field(default_factory=list)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.links: list[tuple[str, dict[str, str], str | None, int, int]] = []
        self._anchors: list[_PendingAnchor] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in _LINK_TAGS:
            return
        values = _attrs(attrs)
        if not values.get("href", "").strip():
            return
        line, offset = self.getpos()
        if normalized_tag == "a":
            self._anchors.append(_PendingAnchor(values, line, offset))
            return
        self.links.append((normalized_tag, values, None, line, offset))

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        normalized_tag = tag.lower()
        if normalized_tag not in _LINK_TAGS:
            return
        values = _attrs(attrs)
        if not values.get("href", "").strip():
            return
        line, offset = self.getpos()
        self.links.append((normalized_tag, values, None, line, offset))

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() != "a" or not self._anchors:
            return
        anchor = self._anchors.pop()
        label = " ".join("".join(anchor.text_parts).split()) or None
        self.links.append(("a", anchor.attrs, label, anchor.line, anchor.offset))

    def handle_data(self, data: str) -> None:
        if self._anchors:
            self._anchors[-1].text_parts.append(data)

    def close(self) -> None:
        super().close()
        while self._anchors:
            anchor = self._anchors.pop()
            label = " ".join("".join(anchor.text_parts).split()) or None
            self.links.append(("a", anchor.attrs, label, anchor.line, anchor.offset))


class HtmlResourceLinkDiscoverer:
    """Discover source-observed HTTP(S) links without assigning research identity."""

    name = "html_link_discovery"
    version = "1"
    manifest = CapabilityManifest(
        adapter_name=name,
        adapter_kind=AdapterKind.CRAWLER,
        version=version,
        capabilities=frozenset({Capability.LINK_DISCOVERY}),
        media_types=frozenset({"text/html", "application/xhtml+xml"}),
    )

    def discover(
        self,
        observation: SourceObservation,
        *,
        html: str,
        base_uri: str,
    ) -> tuple[ResourceLinkObservation, ...]:
        """Resolve page links and preserve safe, source-local link observations."""
        if not isinstance(observation, SourceObservation):
            raise ValueError("link discovery observation must be a SourceObservation")
        if not isinstance(html, str):
            raise ValueError("link discovery HTML must be a string")
        base = normalize_http_uri(base_uri, field_name="base URI")
        base_host = urlsplit(base).hostname

        parser = _LinkParser()
        parser.feed(html)
        parser.close()

        values: list[ResourceLinkObservation] = []
        for tag, attrs, label, line, offset in sorted(
            parser.links,
            key=lambda item: (item[3], item[4]),
        ):
            raw_target = urljoin(base, attrs["href"])
            parsed = urlsplit(raw_target)
            if parsed.scheme.lower() not in {"http", "https"} or not parsed.hostname:
                continue
            try:
                target = normalize_http_uri(raw_target, field_name="resource target URI")
            except ValueError:
                continue
            target_host = urlsplit(target).hostname
            relation = _relation(attrs)
            rel_tokens = tuple(sorted(set(attrs.get("rel", "").lower().split())))
            scope = (
                "internal"
                if target_host is not None
                and base_host is not None
                and target_host.lower() == base_host.lower()
                else "outbound"
            )
            ordinal = len(values)
            values.append(
                ResourceLinkObservation(
                    link_id=_stable_link_id(observation.observation_id, ordinal, target),
                    observation_id=observation.observation_id,
                    target_uri=target,
                    relation=relation,
                    media_type=attrs.get("type") or None,
                    label=label,
                    metadata={
                        "tag": tag,
                        "rel": rel_tokens,
                        "scope": scope,
                        "source_line": line,
                        "source_offset": offset,
                    },
                )
            )
        return tuple(values)


def _attrs(attrs: list[tuple[str, str | None]]) -> dict[str, str]:
    return {key.lower(): value or "" for key, value in attrs}


def _relation(attrs: dict[str, str]) -> ResourceRelation:
    rel = set(attrs.get("rel", "").lower().split())
    if "canonical" in rel:
        return ResourceRelation.CANONICAL
    if "alternate" in rel:
        return ResourceRelation.ALTERNATE
    if "supplement" in rel or "supplementary" in rel:
        return ResourceRelation.SUPPLEMENT
    if "dataset" in rel:
        return ResourceRelation.DATASET
    if "software" in rel:
        return ResourceRelation.SOFTWARE
    return ResourceRelation.RELATED


def _stable_link_id(observation_id: UUID, ordinal: int, target_uri: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"tarkka:{observation_id}:web-link:{ordinal}:{target_uri}",
    )
