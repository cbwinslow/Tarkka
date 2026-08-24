from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath
from uuid import NAMESPACE_URL, uuid5

from tarkka.domain.models import Artifact


class LocalArtifactStore:
    """Immutable, content-addressed artifact storage using SHA-256 paths."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _digest_file(source: Path) -> tuple[str, int]:
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @staticmethod
    def storage_key_for_digest(sha256: str) -> PurePosixPath:
        return PurePosixPath("sha256", sha256[:2], sha256[2:4], sha256)

    def put_file(self, source: Path) -> Artifact:
        source = source.expanduser().resolve()
        if not source.is_file():
            raise FileNotFoundError(source)

        sha256, size = self._digest_file(source)
        key = self.storage_key_for_digest(sha256)
        destination = self._destination(key)
        if not destination.exists():
            fd, temp_name = tempfile.mkstemp(prefix=".tarkka-", dir=destination.parent)
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                shutil.copyfile(source, temp_path)
                if self._digest_file(temp_path)[0] != sha256:
                    raise OSError("artifact checksum changed while copying")
                with temp_path.open("rb") as handle:
                    os.fsync(handle.fileno())
                os.replace(temp_path, destination)
                _fsync_directory(destination.parent)
            finally:
                temp_path.unlink(missing_ok=True)

        media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return self._artifact(
            sha256=sha256,
            size=size,
            key=key,
            media_type=media_type,
            original_name=source.name,
            source_uri=source.as_uri(),
        )

    def put_bytes(
        self,
        data: bytes,
        *,
        original_name: str | None = None,
        source_uri: str | None = None,
        media_type: str = "application/octet-stream",
    ) -> Artifact:
        """Persist immutable bytes while preserving their original remote provenance."""
        if not isinstance(data, bytes):
            raise ValueError("artifact data must be bytes")
        if original_name is not None and (
            not isinstance(original_name, str) or not original_name.strip()
        ):
            raise ValueError("artifact original_name must be non-blank when provided")
        if source_uri is not None and (
            not isinstance(source_uri, str) or not source_uri.strip()
        ):
            raise ValueError("artifact source_uri must be non-blank when provided")
        if not isinstance(media_type, str) or not media_type.strip():
            raise ValueError("artifact media_type must be non-blank")

        sha256 = hashlib.sha256(data).hexdigest()
        key = self.storage_key_for_digest(sha256)
        destination = self._destination(key)
        if not destination.exists():
            fd, temp_name = tempfile.mkstemp(prefix=".tarkka-", dir=destination.parent)
            temp_path = Path(temp_name)
            try:
                with os.fdopen(fd, "wb") as handle:
                    handle.write(data)
                    handle.flush()
                    os.fsync(handle.fileno())
                os.replace(temp_path, destination)
                _fsync_directory(destination.parent)
            finally:
                temp_path.unlink(missing_ok=True)

        return self._artifact(
            sha256=sha256,
            size=len(data),
            key=key,
            media_type=media_type.strip(),
            original_name=original_name.strip() if original_name else None,
            source_uri=source_uri.strip() if source_uri else None,
        )

    def _destination(self, key: PurePosixPath) -> Path:
        destination = self.root.joinpath(*key.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    @staticmethod
    def _artifact(
        *,
        sha256: str,
        size: int,
        key: PurePosixPath,
        media_type: str,
        original_name: str | None,
        source_uri: str | None,
    ) -> Artifact:
        return Artifact(
            artifact_id=uuid5(NAMESPACE_URL, f"urn:sha256:{sha256}"),
            sha256=sha256,
            size_bytes=size,
            media_type=media_type,
            storage_key=key,
            original_name=original_name,
            source_uri=source_uri,
        )

    def path_for(self, artifact: Artifact) -> Path:
        path = self.root.joinpath(*artifact.storage_key.parts)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def read_bytes(self, artifact: Artifact) -> bytes:
        return self.path_for(artifact).read_bytes()

    def read_bytes_by_sha256(self, sha256: str) -> bytes:
        """Read content-addressed bytes and verify the durable object still matches its key."""
        _require_sha256(sha256)
        key = self.storage_key_for_digest(sha256)
        path = self.root.joinpath(*key.parts)
        if not path.is_file():
            raise FileNotFoundError(path)
        data = path.read_bytes()
        if hashlib.sha256(data).hexdigest() != sha256:
            raise OSError("artifact content does not match its SHA-256 storage key")
        return data

    def exists(self, sha256: str) -> bool:
        key = self.storage_key_for_digest(sha256)
        return self.root.joinpath(*key.parts).is_file()


def _require_sha256(value: str) -> None:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise ValueError("artifact SHA-256 must be lowercase hexadecimal")


def _fsync_directory(path: Path) -> None:
    """Flush a renamed directory entry where the platform exposes POSIX directory fsync."""
    if os.name != "posix":
        return
    flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    directory_fd = os.open(path, flags)
    try:
        os.fsync(directory_fd)
    finally:
        os.close(directory_fd)
