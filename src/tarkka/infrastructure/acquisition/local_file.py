from __future__ import annotations

import hashlib
import mimetypes
import os
import stat
from pathlib import Path
from typing import BinaryIO
from urllib.parse import unquote, urlsplit

from tarkka.domain.path_safety import portable_filename_component
from tarkka.domain.source_observations import AdapterKind, Capability, CapabilityManifest
from tarkka.ports.acquisitions import (
    AcquiredArtifact,
    AcquisitionDecision,
    AcquisitionDecisionStatus,
    AcquisitionError,
    AcquisitionFailureKind,
    ArtifactCandidate,
)


class LocalFileAcquirer:
    """Stream regular local files through the generic acquisition contract.

    This adapter deliberately accepts only local ``file:`` URIs. It is not a network-share,
    directory-walking, parser-routing, or Artifact-persistence implementation. Symlink spelling
    remains the source/final URI and filename provenance; opening follows normal OS semantics.
    """

    def __init__(self, *, chunk_size_bytes: int = 1024 * 1024) -> None:
        if (
            not isinstance(chunk_size_bytes, int)
            or isinstance(chunk_size_bytes, bool)
            or chunk_size_bytes <= 0
        ):
            raise ValueError("chunk_size_bytes must be a positive integer")
        self._chunk_size_bytes = chunk_size_bytes

    @property
    def manifest(self) -> CapabilityManifest:
        return _MANIFEST

    def assess(self, candidate: ArtifactCandidate) -> AcquisitionDecision:
        try:
            path = _local_path_from_uri(candidate.source_uri)
        except ValueError as exc:
            return AcquisitionDecision(AcquisitionDecisionStatus.UNSUPPORTED, str(exc))
        try:
            source_stat = path.stat()
        except FileNotFoundError:
            return AcquisitionDecision(
                AcquisitionDecisionStatus.UNAVAILABLE,
                "local source is missing or is not a regular file",
            )
        except PermissionError:
            return AcquisitionDecision(
                AcquisitionDecisionStatus.POLICY_DENIED,
                "local source access is denied",
            )
        except OSError as exc:
            return AcquisitionDecision(
                AcquisitionDecisionStatus.UNAVAILABLE,
                f"local source cannot be inspected: {type(exc).__name__}",
            )
        if not stat.S_ISREG(source_stat.st_mode):
            return AcquisitionDecision(
                AcquisitionDecisionStatus.UNAVAILABLE,
                "local source is missing or is not a regular file",
            )
        return AcquisitionDecision(AcquisitionDecisionStatus.SUPPORTED)

    def acquire(self, candidate: ArtifactCandidate, sink: BinaryIO) -> AcquiredArtifact:
        try:
            requested_path = _local_path_from_uri(candidate.source_uri)
            raw_filename = requested_path.name
            filename = portable_filename_component(raw_filename)
            digest = hashlib.sha256()
            size_bytes = 0
            with requested_path.open("rb") as handle:
                if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                    raise FileNotFoundError(requested_path)
                while chunk := handle.read(self._chunk_size_bytes):
                    _write_all(sink, chunk)
                    digest.update(chunk)
                    size_bytes += len(chunk)
        except (FileNotFoundError, IsADirectoryError) as exc:
            raise AcquisitionError(
                AcquisitionFailureKind.UNAVAILABLE,
                "local source is no longer available",
            ) from exc
        except PermissionError as exc:
            raise AcquisitionError(
                AcquisitionFailureKind.POLICY_DENIED,
                "local source access is denied",
            ) from exc
        except OSError as exc:
            raise AcquisitionError(
                AcquisitionFailureKind.TRANSIENT,
                f"local source read failed: {type(exc).__name__}",
            ) from exc

        metadata = {"source_filename": raw_filename} if filename != raw_filename else {}
        media_type = mimetypes.guess_type(raw_filename)[0]
        return AcquiredArtifact(
            requested_uri=candidate.source_uri,
            final_uri=requested_path.as_uri(),
            size_bytes=size_bytes,
            sha256=digest.hexdigest(),
            media_type=media_type,
            filename=filename,
            metadata=metadata,
        )


def _local_path_from_uri(source_uri: str) -> Path:
    """Translate one intentionally local, absolute file URI into an OS path."""
    parsed = urlsplit(source_uri)
    if parsed.scheme.lower() != "file":
        raise ValueError("local file acquirer supports only file URIs")
    if parsed.netloc.lower() not in {"", "localhost"}:
        raise ValueError("local file acquirer does not support remote file authorities")
    if parsed.query or parsed.fragment:
        raise ValueError("local file URI must not contain a query or fragment")
    path_text = _normalize_file_uri_path(unquote(parsed.path), is_windows=os.name == "nt")
    if not path_text or any(
        ord(character) < 0x20 or ord(character) == 0x7F for character in path_text
    ):
        raise ValueError("local file URI path is invalid")
    path = Path(path_text)
    if not path.is_absolute():
        raise ValueError("local file URI path must be absolute")
    return path


def _normalize_file_uri_path(path_text: str, *, is_windows: bool) -> str:
    """Remove the URI-only leading slash from an absolute Windows drive path."""
    if (
        is_windows
        and len(path_text) >= 3
        and path_text[0] == "/"
        and path_text[1].isalpha()
        and path_text[2] == ":"
    ):
        return path_text[1:]
    return path_text


def _write_all(sink: BinaryIO, chunk: bytes) -> None:
    """Write one source chunk completely without taking ownership of the sink."""
    offset = 0
    while offset < len(chunk):
        written = sink.write(chunk[offset:])
        if not isinstance(written, int) or isinstance(written, bool) or written <= 0:
            raise OSError("acquisition sink did not accept source bytes")
        offset += written


_MANIFEST = CapabilityManifest(
    adapter_name="local-file",
    adapter_kind=AdapterKind.ACQUISITION,
    version="1",
    capabilities=frozenset({Capability.ACQUIRE}),
    identifier_schemes=frozenset({"file"}),
)
