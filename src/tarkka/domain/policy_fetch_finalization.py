from __future__ import annotations

from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from tarkka.domain.http_observations import HttpResponseSnapshot, normalize_http_uri


@dataclass(frozen=True, slots=True)
class PolicyFetchFinalization:
    """Durable intent for one policy-fetch output commit.

    The record contains only sanitized HTTP provenance plus expected content identity. It is
    persisted before artifact/observation writes so restart recovery can distinguish a partial
    commit from a fetch that never reached output finalization.
    """

    checkpoint_id: UUID
    requested_uri: str
    artifact_sha256: str
    observation_id: UUID
    response: HttpResponseSnapshot

    def __post_init__(self) -> None:
        if not isinstance(self.checkpoint_id, UUID):
            raise ValueError("policy finalization checkpoint_id must be a UUID")
        requested_uri = normalize_http_uri(
            self.requested_uri,
            field_name="policy finalization requested URI",
        )
        if requested_uri != self.response.requested_uri:
            raise ValueError("policy finalization response must match requested URI")
        if (
            not isinstance(self.artifact_sha256, str)
            or len(self.artifact_sha256) != 64
            or any(character not in "0123456789abcdef" for character in self.artifact_sha256)
        ):
            raise ValueError("policy finalization artifact_sha256 must be lowercase SHA-256")
        if not isinstance(self.observation_id, UUID):
            raise ValueError("policy finalization observation_id must be a UUID")
        expected_id = uuid5(NAMESPACE_URL, f"urn:sha256:{self.artifact_sha256}")
        expected_observation = self.response.to_source_observation(
            native_artifact_id=expected_id
        )
        if expected_observation.observation_id != self.observation_id:
            raise ValueError("policy finalization observation identity is inconsistent")
        object.__setattr__(self, "requested_uri", requested_uri)

    @property
    def finalization_id(self) -> UUID:
        return uuid5(
            NAMESPACE_URL,
            f"tarkka:{self.checkpoint_id}:policy-finalization:{self.requested_uri}",
        )
