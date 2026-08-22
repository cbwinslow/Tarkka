from __future__ import annotations

from dataclasses import dataclass
from email.utils import parsedate_to_datetime
from urllib.parse import urljoin
from uuid import NAMESPACE_URL, UUID, uuid5
from xml.etree import ElementTree as ET

from tarkka.domain.http_observations import normalize_http_uri
from tarkka.domain.source_observations import (
    AdapterKind,
    Capability,
    CapabilityManifest,
    ResourceLinkObservation,
    ResourceRelation,
    SourceObservation,
)


@dataclass(frozen=True, slots=True)
class _DiscoveredTarget:
    target_uri: str
    relation: ResourceRelation
    media_type: str | None
    label: str | None
    metadata: dict[str, str | int | None]


class SitemapFeedDiscoverer:
    """Preserve URL discovery facts from sitemap, RSS, and Atom XML resources."""

    name = "sitemap_feed_discovery"
    version = "1"
    manifest = CapabilityManifest(
        adapter_name=name,
        adapter_kind=AdapterKind.DISCOVERY,
        version=version,
        capabilities=frozenset(
            {
                Capability.LINK_DISCOVERY,
                Capability.SITEMAPS,
                Capability.FEEDS,
            }
        ),
        media_types=frozenset(
            {
                "application/xml",
                "text/xml",
                "application/rss+xml",
                "application/atom+xml",
            }
        ),
    )

    def discover(
        self,
        observation: SourceObservation,
        *,
        xml: str,
        source_uri: str,
    ) -> tuple[ResourceLinkObservation, ...]:
        """Return deterministic source-observed links from one XML discovery document."""
        if not isinstance(observation, SourceObservation):
            raise ValueError("discovery observation must be a SourceObservation")
        if not isinstance(xml, str):
            raise ValueError("discovery XML must be a string")
        source = normalize_http_uri(source_uri, field_name="discovery source URI")
        try:
            root = ET.fromstring(xml)
        except ET.ParseError as exc:
            raise ValueError(f"unable to parse sitemap/feed XML: {exc}") from exc

        root_name = _local_name(root.tag)
        if root_name == "urlset":
            targets = _sitemap_urlset(root)
        elif root_name == "sitemapindex":
            targets = _sitemap_index(root)
        elif root_name == "rss":
            targets = _rss_feed(root)
        elif root_name == "feed":
            targets = _atom_feed(root)
        else:
            raise ValueError(f"unsupported sitemap/feed root element: {root_name or root.tag}")

        values: list[ResourceLinkObservation] = []
        for source_ordinal, target in enumerate(targets):
            try:
                resolved_target = urljoin(source, target.target_uri)
                normalized_target = normalize_http_uri(
                    resolved_target,
                    field_name="discovered target URI",
                )
            except ValueError:
                # One malformed discovery target must not poison later entries.
                continue
            metadata = dict(target.metadata)
            metadata["source_uri"] = source
            metadata["source_ordinal"] = source_ordinal
            values.append(
                ResourceLinkObservation(
                    link_id=_stable_link_id(
                        observation.observation_id,
                        source_ordinal,
                        normalized_target,
                    ),
                    observation_id=observation.observation_id,
                    target_uri=normalized_target,
                    relation=target.relation,
                    media_type=target.media_type,
                    label=target.label,
                    metadata=metadata,
                )
            )
        return tuple(values)


def _sitemap_urlset(root: ET.Element) -> tuple[_DiscoveredTarget, ...]:
    values: list[_DiscoveredTarget] = []
    for element in _children(root, "url"):
        loc = _child_text(element, "loc")
        if not loc:
            continue
        values.append(
            _DiscoveredTarget(
                target_uri=loc,
                relation=ResourceRelation.RELATED,
                media_type=None,
                label=None,
                metadata={
                    "discovery_kind": "sitemap_url",
                    "last_modified": _child_text(element, "lastmod"),
                },
            )
        )
    return tuple(values)


def _sitemap_index(root: ET.Element) -> tuple[_DiscoveredTarget, ...]:
    values: list[_DiscoveredTarget] = []
    for element in _children(root, "sitemap"):
        loc = _child_text(element, "loc")
        if not loc:
            continue
        values.append(
            _DiscoveredTarget(
                target_uri=loc,
                relation=ResourceRelation.RELATED,
                media_type="application/xml",
                label=None,
                metadata={
                    "discovery_kind": "sitemap_index",
                    "last_modified": _child_text(element, "lastmod"),
                },
            )
        )
    return tuple(values)


def _rss_feed(root: ET.Element) -> tuple[_DiscoveredTarget, ...]:
    channel = next(iter(_children(root, "channel")), None)
    if channel is None:
        return ()
    values: list[_DiscoveredTarget] = []
    for item in _children(channel, "item"):
        link = _child_text(item, "link")
        if not link:
            continue
        published = _child_text(item, "pubDate")
        values.append(
            _DiscoveredTarget(
                target_uri=link,
                relation=ResourceRelation.RELATED,
                media_type=None,
                label=_child_text(item, "title"),
                metadata={
                    "discovery_kind": "rss_item",
                    "entry_id": _child_text(item, "guid"),
                    "published_at": published,
                    "published_at_normalized": _normalize_rss_datetime(published),
                },
            )
        )
    return tuple(values)


def _atom_feed(root: ET.Element) -> tuple[_DiscoveredTarget, ...]:
    values: list[_DiscoveredTarget] = []
    for entry in _children(root, "entry"):
        entry_id = _child_text(entry, "id")
        title = _child_text(entry, "title")
        published = _child_text(entry, "published")
        updated = _child_text(entry, "updated")
        for link in _children(entry, "link"):
            href = (link.attrib.get("href") or "").strip()
            if not href:
                continue
            rel = (link.attrib.get("rel") or "alternate").strip().lower()
            relation = (
                ResourceRelation.ALTERNATE
                if rel == "alternate"
                else ResourceRelation.RELATED
            )
            values.append(
                _DiscoveredTarget(
                    target_uri=href,
                    relation=relation,
                    media_type=(link.attrib.get("type") or "").strip() or None,
                    label=title,
                    metadata={
                        "discovery_kind": "atom_entry",
                        "entry_id": entry_id,
                        "feed_rel": rel,
                        "published_at": published,
                        "updated_at": updated,
                    },
                )
            )
    return tuple(values)


def _children(element: ET.Element, name: str) -> tuple[ET.Element, ...]:
    target_name = name.lower()
    return tuple(child for child in element if _local_name(child.tag) == target_name)


def _child_text(element: ET.Element, name: str) -> str | None:
    target_name = name.lower()
    for child in element:
        if _local_name(child.tag) != target_name:
            continue
        value = " ".join("".join(child.itertext()).split())
        return value or None
    return None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def _normalize_rss_datetime(value: str | None) -> str | None:
    if value is None:
        return None
    try:
        parsed = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return parsed.isoformat()


def _stable_link_id(observation_id: UUID, ordinal: int, target_uri: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"tarkka:{observation_id}:discovery-link:{ordinal}:{target_uri}",
    )
