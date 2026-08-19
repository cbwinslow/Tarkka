from __future__ import annotations

import hashlib
import mimetypes
import os
import shutil
import tempfile
from pathlib import Path, PurePosixPath

from tarkka.domain.models import Artifact, new_id


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
        destination = self.root.joinpath(*key.parts)
        destination.parent.mkdir(parents=True, exist_ok=True)

        if not destination.exists():
            fd, temp_name = tempfile.mkstemp(prefix=".tarkka-", dir=destination.parent)
            os.close(fd)
            temp_path = Path(temp_name)
            try:
                shutil.copyfile(source, temp_path)
                if self._digest_file(temp_path)[0] != sha256:
                    raise OSError("artifact checksum changed while copying")
                os.replace(temp_path, destination)
            finally:
                temp_path.unlink(missing_ok=True)

        media_type = mimetypes.guess_type(source.name)[0] or "application/octet-stream"
        return Artifact(
            artifact_id=new_id(),
            sha256=sha256,
            size_bytes=size,
            media_type=media_type,
            storage_key=key,
            original_name=source.name,
            source_uri=source.as_uri(),
        )

    def path_for(self, artifact: Artifact) -> Path:
        path = self.root.joinpath(*artifact.storage_key.parts)
        if not path.is_file():
            raise FileNotFoundError(path)
        return path

    def read_bytes(self, artifact: Artifact) -> bytes:
        return self.path_for(artifact).read_bytes()

    def exists(self, sha256: str) -> bool:
        key = self.storage_key_for_digest(sha256)
        return self.root.joinpath(*key.parts).is_file()
