from __future__ import annotations

import hashlib
from io import BytesIO
from typing import cast

import pytest

from tarkka.domain.source_observations import AdapterKind, Capability, CapabilityManifest
from tarkka.ports.acquisitions import (
    AcquiredArtifact,
    AcquisitionDecision,
    AcquisitionDecisionStatus,
    AcquisitionError,
    AcquisitionFailureKind,
    ArtifactAcquirer,
    ArtifactCandidate,
    assess_acquisition_adapters,
)

pytestmark = [pytest.mark.unit, pytest.mark.regression]


def _manifest(
    name: str,
    *,
    capabilities: frozenset[Capability] = frozenset({Capability.ACQUIRE}),
) -> CapabilityManifest:
    return CapabilityManifest(
        adapter_name=name,
        adapter_kind=AdapterKind.ACQUISITION,
        version="1",
        capabilities=capabilities,
    )


class _StreamingAcquirer:
    def __init__(
        self,
        name: str,
        payload: bytes,
        decision: AcquisitionDecision,
        *,
        capabilities: frozenset[Capability] = frozenset({Capability.ACQUIRE}),
    ) -> None:
        self.manifest = _manifest(name, capabilities=capabilities)
        self._payload = payload
        self._decision = decision
        self.assess_calls = 0

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision:
        assert candidate.source_uri
        self.assess_calls += 1
        return self._decision

    def acquire(self, candidate: ArtifactCandidate, sink: BytesIO) -> AcquiredArtifact:
        for offset in range(0, len(self._payload), 3):
            sink.write(self._payload[offset : offset + 3])
        return AcquiredArtifact(
            requested_uri=candidate.source_uri,
            final_uri=candidate.source_uri,
            size_bytes=len(self._payload),
            sha256=hashlib.sha256(self._payload).hexdigest(),
            media_type=candidate.media_type_hint,
            filename=candidate.filename_hint,
            metadata={"adapter": self.manifest.adapter_name},
        )


class _MustNotAssess:
    manifest = _manifest("non-acquirer", capabilities=frozenset({Capability.SEARCH}))

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision:
        raise AssertionError(f"non-ACQUIRE adapter was assessed: {candidate.source_uri}")

    def acquire(self, candidate: ArtifactCandidate, sink: BytesIO) -> AcquiredArtifact:
        raise AssertionError(f"non-ACQUIRE adapter was invoked: {candidate.source_uri}")


def test_artifact_candidate_normalizes_scheme_and_freezes_metadata() -> None:
    metadata = {"provider_record": "abc-123"}
    candidate = ArtifactCandidate(
        source_uri="HTTPS://example.test/paper",
        media_type_hint="application/pdf",
        filename_hint="paper.pdf",
        expected_size_bytes=17,
        metadata=metadata,
    )
    metadata["provider_record"] = "changed"

    assert candidate.uri_scheme == "https"
    assert candidate.metadata == {"provider_record": "abc-123"}
    with pytest.raises(TypeError):
        candidate.metadata["new"] = "value"  # type: ignore[index]


@pytest.mark.parametrize(
    "source_uri",
    ["", "relative/path", "1bad://example.test", "https://[broken"],
)
def test_artifact_candidate_rejects_invalid_source_uri(source_uri: str) -> None:
    with pytest.raises(ValueError, match="source URI must be an absolute URI"):
        ArtifactCandidate(source_uri=source_uri)


@pytest.mark.parametrize(
    ("field", "kwargs"),
    [
        ("media type hint", {"media_type_hint": " "}),
        ("filename hint", {"filename_hint": ""}),
    ],
)
def test_artifact_candidate_rejects_blank_optional_hints(
    field: str,
    kwargs: dict[str, str],
) -> None:
    with pytest.raises(ValueError, match=field):
        ArtifactCandidate(source_uri="file:///tmp/source", **kwargs)


@pytest.mark.parametrize("expected_size_bytes", [-1, True])
def test_artifact_candidate_rejects_invalid_expected_size(expected_size_bytes: int) -> None:
    with pytest.raises(ValueError, match="expected_size_bytes must be a non-negative integer"):
        ArtifactCandidate(
            source_uri="file:///tmp/source",
            expected_size_bytes=expected_size_bytes,
        )


@pytest.mark.parametrize(
    "metadata",
    [
        cast(dict[str, str], []),
        {"": "value"},
        cast(dict[str, str], {1: "value"}),
        cast(dict[str, str], {"key": 1}),
    ],
)
def test_artifact_candidate_rejects_invalid_metadata(metadata: dict[str, str]) -> None:
    with pytest.raises(ValueError, match="acquisition metadata"):
        ArtifactCandidate(source_uri="file:///tmp/source", metadata=metadata)


def test_acquisition_decision_exposes_supported_state() -> None:
    supported = AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED)
    supported_with_reason = AcquisitionDecision(
        AcquisitionDecisionStatus.SUPPORTED,
        "preferred representation",
    )
    denied = AcquisitionDecision(
        AcquisitionDecisionStatus.POLICY_DENIED,
        "rights policy blocks retrieval",
    )

    assert supported.supported is True
    assert supported_with_reason.supported is True
    assert denied.supported is False


@pytest.mark.parametrize(
    "status",
    [
        AcquisitionDecisionStatus.UNSUPPORTED,
        AcquisitionDecisionStatus.POLICY_DENIED,
        AcquisitionDecisionStatus.UNAVAILABLE,
    ],
)
def test_non_supported_acquisition_decision_requires_reason(
    status: AcquisitionDecisionStatus,
) -> None:
    with pytest.raises(ValueError, match="require a reason"):
        AcquisitionDecision(status)


def test_acquisition_decision_rejects_invalid_status_and_blank_reason() -> None:
    with pytest.raises(ValueError, match="must be an AcquisitionDecisionStatus"):
        AcquisitionDecision(cast(AcquisitionDecisionStatus, "supported"))
    with pytest.raises(ValueError, match="reason must be a non-blank string"):
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED, " ")


@pytest.mark.parametrize(
    ("kind", "retryable"),
    [
        (AcquisitionFailureKind.UNSUPPORTED, False),
        (AcquisitionFailureKind.POLICY_DENIED, False),
        (AcquisitionFailureKind.TRANSIENT, True),
        (AcquisitionFailureKind.UNAVAILABLE, False),
    ],
)
def test_acquisition_error_has_stable_retry_semantics(
    kind: AcquisitionFailureKind,
    retryable: bool,
) -> None:
    error = AcquisitionError(kind, "source acquisition failed")

    assert error.kind is kind
    assert error.retryable is retryable
    assert str(error) == "source acquisition failed"


def test_acquisition_error_rejects_invalid_kind_and_message() -> None:
    with pytest.raises(ValueError, match="kind must be an AcquisitionFailureKind"):
        AcquisitionError(cast(AcquisitionFailureKind, "transient"), "failed")
    with pytest.raises(ValueError, match="message must be a non-blank string"):
        AcquisitionError(AcquisitionFailureKind.TRANSIENT, " ")


def test_acquired_artifact_accepts_direct_and_redirected_receipts() -> None:
    direct = AcquiredArtifact(
        requested_uri="file:///tmp/paper.pdf",
        final_uri="file:///tmp/paper.pdf",
        size_bytes=0,
        sha256=hashlib.sha256(b"").hexdigest(),
        media_type="application/pdf",
        filename="paper.pdf",
        metadata={"source": "local"},
    )
    redirected = AcquiredArtifact(
        requested_uri="https://example.test/latest",
        final_uri="https://cdn.example.test/paper.pdf",
        size_bytes=3,
        sha256=hashlib.sha256(b"pdf").hexdigest(),
        redirect_chain=(
            "https://example.test/download",
            "https://cdn.example.test/paper.pdf",
        ),
    )

    assert direct.redirect_chain == ()
    assert direct.metadata == {"source": "local"}
    assert redirected.redirect_chain[-1] == redirected.final_uri
    with pytest.raises(TypeError):
        direct.metadata["new"] = "value"  # type: ignore[index]


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"requested_uri": "relative"}, "requested URI"),
        ({"final_uri": "https://[broken"}, "final URI"),
        ({"size_bytes": -1}, "size_bytes must be a non-negative integer"),
        ({"size_bytes": True}, "size_bytes must be a non-negative integer"),
        ({"sha256": "A" * 64}, "sha256 must be 64 lowercase hexadecimal"),
        ({"sha256": "g" * 64}, "sha256 must be 64 lowercase hexadecimal"),
        ({"media_type": " "}, "media type must be a non-blank string"),
        ({"filename": ""}, "filename must be a non-blank string"),
    ],
)
def test_acquired_artifact_rejects_invalid_scalar_fields(
    kwargs: dict[str, object],
    message: str,
) -> None:
    values: dict[str, object] = {
        "requested_uri": "https://example.test/source",
        "final_uri": "https://example.test/source",
        "size_bytes": 3,
        "sha256": hashlib.sha256(b"abc").hexdigest(),
    }
    values.update(kwargs)

    with pytest.raises(ValueError, match=message):
        AcquiredArtifact(**values)  # type: ignore[arg-type]


def test_acquired_artifact_rejects_invalid_redirect_semantics() -> None:
    digest = hashlib.sha256(b"abc").hexdigest()

    with pytest.raises(ValueError, match="redirect chain must contain valid URIs"):
        AcquiredArtifact(
            requested_uri="https://example.test/source",
            final_uri="https://example.test/final",
            size_bytes=3,
            sha256=digest,
            redirect_chain=("relative",),
        )
    with pytest.raises(ValueError, match="unchanged acquired URI"):
        AcquiredArtifact(
            requested_uri="https://example.test/source",
            final_uri="https://example.test/source",
            size_bytes=3,
            sha256=digest,
            redirect_chain=("https://example.test/source",),
        )
    with pytest.raises(ValueError, match="must end its redirect chain"):
        AcquiredArtifact(
            requested_uri="https://example.test/source",
            final_uri="https://example.test/final",
            size_bytes=3,
            sha256=digest,
        )
    with pytest.raises(ValueError, match="must end its redirect chain"):
        AcquiredArtifact(
            requested_uri="https://example.test/source",
            final_uri="https://example.test/final",
            size_bytes=3,
            sha256=digest,
            redirect_chain=("https://example.test/elsewhere",),
        )


def test_acquired_artifact_rejects_invalid_metadata() -> None:
    with pytest.raises(ValueError, match="metadata values must be strings"):
        AcquiredArtifact(
            requested_uri="file:///tmp/source",
            final_uri="file:///tmp/source",
            size_bytes=0,
            sha256=hashlib.sha256(b"").hexdigest(),
            metadata=cast(dict[str, str], {"count": 1}),
        )


def test_structural_acquirer_streams_into_caller_owned_sink() -> None:
    payload = b"provider-neutral acquisition bytes"
    implementation = _StreamingAcquirer(
        "opaque-adapter-name",
        payload,
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED),
    )
    acquirer: ArtifactAcquirer = implementation
    candidate = ArtifactCandidate(
        source_uri="custom+research://source/record/42",
        media_type_hint="application/octet-stream",
        filename_hint="record.bin",
    )
    sink = BytesIO()

    receipt = acquirer.acquire(candidate, sink)

    assert sink.getvalue() == payload
    assert receipt.requested_uri == candidate.source_uri
    assert receipt.size_bytes == len(payload)
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.metadata == {"adapter": "opaque-adapter-name"}


def test_capability_assessment_filters_and_preserves_declared_order() -> None:
    candidate = ArtifactCandidate(source_uri="https://example.test/paper")
    first = _StreamingAcquirer(
        "first",
        b"",
        AcquisitionDecision(
            AcquisitionDecisionStatus.UNSUPPORTED,
            "candidate shape not supported",
        ),
    )
    second = _StreamingAcquirer(
        "second",
        b"",
        AcquisitionDecision(
            AcquisitionDecisionStatus.POLICY_DENIED,
            "rights policy denied acquisition",
        ),
    )
    third = _StreamingAcquirer(
        "third",
        b"",
        AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED),
    )
    excluded = _MustNotAssess()

    assessments = assess_acquisition_adapters(
        (first, cast(ArtifactAcquirer, excluded), second, third),
        candidate,
    )

    assert [adapter.manifest.adapter_name for adapter, _ in assessments] == [
        "first",
        "second",
        "third",
    ]
    assert [decision.status for _, decision in assessments] == [
        AcquisitionDecisionStatus.UNSUPPORTED,
        AcquisitionDecisionStatus.POLICY_DENIED,
        AcquisitionDecisionStatus.SUPPORTED,
    ]
    assert first.assess_calls == second.assess_calls == third.assess_calls == 1
