"""Infrastructure adapter that replays an application-built v3 payload in isolation."""

from __future__ import annotations

import tempfile
from pathlib import Path

from tarkka.application.document_replay import DocumentReplayExecutionError
from tarkka.application.proof_bundles import ProofBundlePayload
from tarkka.application.replay import ReplayParserRegistry, ReplayResult
from tarkka.infrastructure.proof_bundles import build_proof_bundle_bytes
from tarkka.infrastructure.replay import ReplayProblem, replay_proof_bundle


class EphemeralProofBundleReplayer:
    """Materialize a private temporary archive and reuse the exact path replay engine."""

    def __init__(self, registry: ReplayParserRegistry) -> None:
        self._registry = registry

    def replay(self, payload: ProofBundlePayload) -> ReplayResult:
        """Execute exact replay without exposing the temporary archive path to callers."""
        try:
            archive_bytes = build_proof_bundle_bytes(payload)
            with tempfile.TemporaryDirectory(prefix="tarkka-document-replay-") as directory:
                path = Path(directory) / "snapshot.tarkka"
                path.write_bytes(archive_bytes)
                return replay_proof_bundle(path, self._registry)
        except ReplayProblem as exc:
            raise DocumentReplayExecutionError(
                exc.code,
                str(exc),
                parser_name=exc.parser_name,
                parser_version=exc.parser_version,
                determinism=exc.determinism,
            ) from exc
        except OSError as exc:
            raise DocumentReplayExecutionError("replay_io_error", str(exc)) from exc
        except (RuntimeError, ValueError) as exc:
            raise DocumentReplayExecutionError("replay_bundle_invalid", str(exc)) from exc
