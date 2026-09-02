from __future__ import annotations

import hashlib
from collections.abc import Mapping
from io import BytesIO
from pathlib import Path

import pytest

from tarkka.application.ingest import IngestService
from tarkka.application.policy_http_exchange import PolicySafeHttpExchange, redirect_location
from tarkka.domain.resource_acquisition import ResourceAcquisitionPolicy
from tarkka.infrastructure.acquisition.http import HttpArtifactAcquirer
from tarkka.infrastructure.storage.acquisition_log import JsonlAcquisitionLog
from tarkka.infrastructure.storage.json_repository import JsonResearchRepository
from tarkka.infrastructure.storage.local_artifacts import LocalArtifactStore
from tarkka.infrastructure.storage.text_parser import PlainTextParser
from tarkka.ports.acquisitions import (
    AcquisitionDecisionStatus,
    AcquisitionError,
    AcquisitionFailureKind,
    ArtifactCandidate,
)
from tarkka.ports.http_transport import HttpTransportResponse

pytestmark = [pytest.mark.unit, pytest.mark.security]

_START = "https://example.org/papers/requested.md"
_FINAL = "https://cdn.example.org/final.md"
_PUBLIC_ADDRESS = "93.184.216.34"


class _Resolver:
    def __init__(self, addresses: Mapping[str, tuple[str, ...]] | None = None) -> None:
        self.addresses = addresses or {
            "example.org": (_PUBLIC_ADDRESS,),
            "cdn.example.org": (_PUBLIC_ADDRESS,),
        }
        self.requests: list[tuple[str, float | None]] = []

    def resolve(self, hostname: str, *, timeout_seconds: float | None = None) -> tuple[str, ...]:
        self.requests.append((hostname, timeout_seconds))
        return self.addresses[hostname]


class _Transport:
    def __init__(self, responses: Mapping[str, HttpTransportResponse] | None = None) -> None:
        self.responses = responses or {_START: HttpTransportResponse(status_code=200, body=b"ok")}
        self.requests: list[tuple[str, str, int, float | None]] = []

    def request(
        self,
        *,
        uri: str,
        resolved_address: str,
        max_response_bytes: int,
        timeout_seconds: float | None = None,
    ) -> HttpTransportResponse:
        self.requests.append((uri, resolved_address, max_response_bytes, timeout_seconds))
        return self.responses[uri]


def _policy(**overrides: object) -> ResourceAcquisitionPolicy:
    values: dict[str, object] = {
        "allowed_domains": frozenset({"example.org"}),
        "max_requests": 3,
        "max_bytes": 128,
        "max_redirects": 2,
        "max_elapsed_seconds": 60.0,
    }
    values.update(overrides)
    return ResourceAcquisitionPolicy(**values)  # type: ignore[arg-type]


def _acquirer(
    *,
    policy: ResourceAcquisitionPolicy | None = None,
    resolver: _Resolver | None = None,
    transport: _Transport | None = None,
    chunk_size_bytes: int = 4,
) -> HttpArtifactAcquirer:
    return HttpArtifactAcquirer(
        exchange=PolicySafeHttpExchange(
            resolver=resolver or _Resolver(), transport=transport or _Transport()
        ),
        policy=policy or _policy(),
        chunk_size_bytes=chunk_size_bytes,
        clock=lambda: 0.0,
        sleeper=lambda _: None,
    )


def test_http_acquirer_redirects_with_policy_checked_dns_and_preserves_receipt() -> None:
    payload = b"# Result\nHTTP provenance.\n"
    resolver = _Resolver()
    transport = _Transport(
        {
            _START: HttpTransportResponse(status_code=302, headers={"location": (_FINAL,)}),
            _FINAL: HttpTransportResponse(
                status_code=200,
                headers={
                    "content-type": ("text/markdown; charset=utf-8",),
                    "etag": ('"version-1"',),
                },
                body=payload,
            ),
        }
    )
    acquirer = _acquirer(policy=_policy(), resolver=resolver, transport=transport)
    sink = BytesIO()

    receipt = acquirer.acquire(ArtifactCandidate(source_uri=_START), sink)

    assert sink.getvalue() == payload
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()
    assert receipt.size_bytes == len(payload)
    assert receipt.requested_uri == _START
    assert receipt.final_uri == _FINAL
    assert receipt.redirect_chain == (_FINAL,)
    assert receipt.filename == "final.md"
    assert receipt.media_type == "text/markdown"
    assert receipt.metadata == {
        "http.status_code": "200",
        "http.declared_content_type": "text/markdown; charset=utf-8",
        "http.etag": '"version-1"',
    }
    assert [request[:2] for request in transport.requests] == [
        (_START, _PUBLIC_ADDRESS),
        (_FINAL, _PUBLIC_ADDRESS),
    ]
    assert [hostname for hostname, _ in resolver.requests] == ["example.org", "cdn.example.org"]


@pytest.mark.parametrize(
    ("uri", "status"),
    (
        ("file:///tmp/paper.md", AcquisitionDecisionStatus.UNSUPPORTED),
        ("https://elsewhere.test/x", AcquisitionDecisionStatus.POLICY_DENIED),
    ),
)
def test_http_assessment_is_network_free_and_distinguishes_unsupported_from_policy_denied(
    uri: str, status: AcquisitionDecisionStatus
) -> None:
    resolver = _Resolver()
    decision = _acquirer(resolver=resolver).assess(ArtifactCandidate(source_uri=uri))

    assert decision.status is status
    assert resolver.requests == []


def test_http_acquirer_rejects_redirect_outside_policy_before_second_request() -> None:
    transport = _Transport(
        {
            _START: HttpTransportResponse(
                status_code=302, headers={"location": ("https://elsewhere.test/paper",)}
            )
        }
    )
    with pytest.raises(AcquisitionError) as error:
        _acquirer(transport=transport).acquire(ArtifactCandidate(source_uri=_START), BytesIO())

    assert error.value.kind is AcquisitionFailureKind.POLICY_DENIED
    assert len(transport.requests) == 1


@pytest.mark.parametrize("value", (0, -1, True))
def test_http_acquirer_rejects_invalid_chunk_size(value: int) -> None:
    with pytest.raises(ValueError, match="chunk_size_bytes"):
        _acquirer(chunk_size_bytes=value)


def test_http_acquirer_denies_zero_request_policy_without_network() -> None:
    resolver = _Resolver()
    acquirer = _acquirer(policy=_policy(max_requests=0), resolver=resolver)
    candidate = ArtifactCandidate(source_uri=_START)

    assert acquirer.assess(candidate).status is AcquisitionDecisionStatus.POLICY_DENIED
    with pytest.raises(AcquisitionError) as error:
        acquirer.acquire(candidate, BytesIO())

    assert error.value.kind is AcquisitionFailureKind.POLICY_DENIED
    assert resolver.requests == []


@pytest.mark.parametrize(
    "headers",
    (
        {},
        {"location": ("",)},
        {"location": ("https://example.org/a", "https://example.org/b")},
    ),
)
def test_http_acquirer_rejects_malformed_redirects(headers: Mapping[str, tuple[str, ...]]) -> None:
    transport = _Transport({_START: HttpTransportResponse(status_code=302, headers=headers)})
    with pytest.raises(AcquisitionError) as error:
        _acquirer(transport=transport).acquire(ArtifactCandidate(source_uri=_START), BytesIO())

    assert error.value.kind is AcquisitionFailureKind.POLICY_DENIED


def test_http_acquirer_enforces_redirect_and_request_budgets() -> None:
    redirect = HttpTransportResponse(status_code=302, headers={"location": (_START,)})
    transport = _Transport({_START: redirect})
    with pytest.raises(AcquisitionError, match="ValueError"):
        _acquirer(policy=_policy(max_redirects=0), transport=transport).acquire(
            ArtifactCandidate(source_uri=_START), BytesIO()
        )
    with pytest.raises(AcquisitionError, match="ValueError"):
        _acquirer(policy=_policy(max_requests=1), transport=transport).acquire(
            ArtifactCandidate(source_uri=_START), BytesIO()
        )


def test_policy_safe_exchange_rejects_invalid_caps_and_unsafe_transport_results() -> None:
    exchange = PolicySafeHttpExchange(resolver=_Resolver(), transport=_Transport())
    policy = _policy()
    with pytest.raises(ValueError, match="byte cap"):
        exchange.request(uri=_START, policy=policy, max_response_bytes=True)
    with pytest.raises(ValueError, match="byte cap"):
        exchange.request(uri=_START, policy=policy, max_response_bytes=-1)
    with pytest.raises(ValueError, match="not allowed"):
        exchange.request(
            uri="https://elsewhere.test/x", policy=policy, max_response_bytes=1
        )
    with pytest.raises(ValueError, match="larger"):
        PolicySafeHttpExchange(
            resolver=_Resolver(),
            transport=_Transport({_START: HttpTransportResponse(status_code=200, body=b"too big")}),
        ).request(uri=_START, policy=policy, max_response_bytes=1)


def test_policy_safe_exchange_rejects_only_disallowed_dns_addresses() -> None:
    exchange = PolicySafeHttpExchange(
        resolver=_Resolver({"example.org": ("127.0.0.1",)}), transport=_Transport()
    )

    with pytest.raises(ValueError, match="only to disallowed"):
        exchange.request(uri=_START, policy=_policy(), max_response_bytes=10)


def test_policy_safe_exchange_rejects_empty_dns_and_malformed_redirect_references() -> None:
    with pytest.raises(ValueError, match="no addresses"):
        PolicySafeHttpExchange(
            resolver=_Resolver({"example.org": ()}), transport=_Transport()
        ).request(uri=_START, policy=_policy(), max_response_bytes=10)
    for location in (
        "bad location",
        "https://example.org/\x01",
        "https://[broken",
        "ftp://example.org/a",
        "//:80/path",
    ):
        with pytest.raises(ValueError):
            response = HttpTransportResponse(
                status_code=302, headers={"location": (location,)}
            )
            redirect_location(response)


@pytest.mark.parametrize(
    ("response", "kind"),
    (
        (HttpTransportResponse(status_code=404), AcquisitionFailureKind.UNAVAILABLE),
        (HttpTransportResponse(status_code=503), AcquisitionFailureKind.TRANSIENT),
        (
            HttpTransportResponse(status_code=200, body=b"cap", limit_exceeded=True),
            AcquisitionFailureKind.POLICY_DENIED,
        ),
    ),
)
def test_http_acquirer_classifies_error_and_limited_responses(
    response: HttpTransportResponse, kind: AcquisitionFailureKind
) -> None:
    with pytest.raises(AcquisitionError) as error:
        _acquirer(transport=_Transport({_START: response})).acquire(
            ArtifactCandidate(source_uri=_START), BytesIO()
        )

    assert error.value.kind is kind


def test_http_acquirer_retries_short_sink_writes() -> None:
    payload = b"short sink writes must not lose HTTP bytes"

    class _ShortSink:
        def __init__(self) -> None:
            self.value = bytearray()

        def write(self, data: bytes) -> int:
            self.value.extend(data[:2])
            return min(2, len(data))

    sink = _ShortSink()
    transport = _Transport({_START: HttpTransportResponse(status_code=200, body=payload)})
    receipt = _acquirer(transport=transport).acquire(
        ArtifactCandidate(source_uri=_START), sink  # type: ignore[arg-type]
    )

    assert bytes(sink.value) == payload
    assert receipt.sha256 == hashlib.sha256(payload).hexdigest()


def test_http_acquirer_maps_transport_and_sink_failures_to_transient() -> None:
    class _BrokenTransport(_Transport):
        def request(
            self, **kwargs: object
        ) -> HttpTransportResponse:
            del kwargs
            raise OSError("offline")

    class _RejectingSink:
        def write(self, data: bytes) -> int:
            del data
            return 0

    with pytest.raises(AcquisitionError) as transport_error:
        _acquirer(transport=_BrokenTransport()).acquire(
            ArtifactCandidate(source_uri=_START), BytesIO()
        )
    with pytest.raises(AcquisitionError) as sink_error:
        _acquirer().acquire(ArtifactCandidate(source_uri=_START), _RejectingSink())  # type: ignore[arg-type]

    assert transport_error.value.kind is AcquisitionFailureKind.TRANSIENT
    assert sink_error.value.kind is AcquisitionFailureKind.TRANSIENT


@pytest.mark.parametrize("status", (401, 403))
def test_http_acquirer_maps_access_denial_to_policy_denied(status: int) -> None:
    transport = _Transport({_START: HttpTransportResponse(status_code=status)})
    with pytest.raises(AcquisitionError) as error:
        _acquirer(transport=transport).acquire(
            ArtifactCandidate(source_uri=_START), BytesIO()
        )

    assert error.value.kind is AcquisitionFailureKind.POLICY_DENIED


def test_http_acquirer_applies_wait_and_elapsed_policy() -> None:
    current_time = [0.0]
    sleeps: list[float] = []
    transport = _Transport(
        {
            _START: HttpTransportResponse(status_code=302, headers={"location": (_FINAL,)}),
            _FINAL: HttpTransportResponse(status_code=200),
        }
    )
    acquirer = HttpArtifactAcquirer(
        exchange=PolicySafeHttpExchange(resolver=_Resolver(), transport=transport),
        policy=_policy(min_request_interval_seconds=1.0),
        clock=lambda: current_time[0],
        sleeper=lambda interval: (
            sleeps.append(interval),
            current_time.__setitem__(0, 60.0),
        ),
    )

    with pytest.raises(AcquisitionError, match="ValueError"):
        acquirer.acquire(ArtifactCandidate(source_uri=_START), BytesIO())

    assert sleeps == [1.0]


def test_http_acquirer_rejects_wait_beyond_remaining_elapsed_budget() -> None:
    transport = _Transport(
        {_START: HttpTransportResponse(status_code=302, headers={"location": (_FINAL,)})}
    )
    with pytest.raises(AcquisitionError, match="ValueError"):
        _acquirer(
            policy=_policy(max_elapsed_seconds=0.5, min_request_interval_seconds=1.0),
            transport=transport,
        ).acquire(ArtifactCandidate(source_uri=_START), BytesIO())


def test_http_acquirer_allows_no_elapsed_limit_and_preserves_unsafe_filename_provenance() -> None:
    final = "https://example.org/unsafe%3Aname.md"
    receipt = _acquirer(
        policy=_policy(max_elapsed_seconds=None),
        transport=_Transport(
            {
                _START: HttpTransportResponse(status_code=302, headers={"location": (final,)}),
                final: HttpTransportResponse(
                    status_code=200,
                    headers={"etag": ("",)},
                ),
            }
        ),
    ).acquire(ArtifactCandidate(source_uri=_START), BytesIO())

    assert receipt.filename == "unsafe_name.md"
    assert receipt.metadata["http.source_filename"] == "unsafe:name.md"


@pytest.mark.parametrize("clock", (lambda: True, lambda: float("inf")))
def test_http_acquirer_rejects_invalid_clock_values(clock: object) -> None:
    acquirer = HttpArtifactAcquirer(
        exchange=PolicySafeHttpExchange(resolver=_Resolver(), transport=_Transport()),
        policy=_policy(),
        clock=clock,  # type: ignore[arg-type]
        sleeper=lambda _: None,
    )
    with pytest.raises(ValueError, match="clock"):
        acquirer.acquire(ArtifactCandidate(source_uri=_START), BytesIO())


def test_http_acquirer_composes_with_ingestion_receipt_provenance_and_idempotency(
    tmp_path: Path,
) -> None:
    payload = b"# Result\nHTTP adapter provenance.\n"
    acquirer = _acquirer(
        transport=_Transport(
            {_START: HttpTransportResponse(status_code=200, body=payload)}
        )
    )
    log = JsonlAcquisitionLog(tmp_path / "acquisitions.jsonl")
    service = IngestService(
        artifact_store=LocalArtifactStore(tmp_path / "artifacts"),
        repository=JsonResearchRepository(tmp_path / "catalog.json"),
        acquisition_recorder=log,
        parsers=(PlainTextParser(),),
    )
    candidate = ArtifactCandidate(source_uri=_START)

    first = service.ingest_candidate(candidate, acquirers=(acquirer,))
    second = service.ingest_candidate(candidate, acquirers=(acquirer,))

    assert first.artifact.artifact_id == second.artifact.artifact_id
    assert first.acquisition.source_uri == _START
    assert first.acquisition.metadata["receipt.requested_uri"] == _START
    assert first.acquisition.metadata["receipt.final_uri"] == _START
    assert first.acquisition.metadata["receipt.sha256"] == first.artifact.sha256
