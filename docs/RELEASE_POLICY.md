# Release and Publication Policy

Tarkka publishes software releases deliberately. This policy defines the initial public channel:
**tagged GitHub Releases**. Tarkka is not currently published on PyPI.

This policy covers Tarkka software and project-authored documentation only. A release must never
bundle acquired research artifacts, local databases, credentials, telemetry, or source content
that Tarkka is not permitted to redistribute.

## Supported channel

The newest non-prerelease GitHub Release is the supported public version. Earlier releases remain
available for reproducibility but receive best-effort support only. A release tag is immutable in
intent: corrections use a new version and release note; maintainers do not replace artifacts under
an existing tag.

Until a separately approved issue changes this policy, releases are created only from `main` and
only after the associated GitHub issue and pull request are complete.

## Versioning

The package version in `pyproject.toml` uses `MAJOR.MINOR.PATCH`; the matching Git tag is prefixed
with `v` (for example, package `0.1.0` is released as `v0.1.0`).

Before `1.0.0`, Tarkka follows these rules:

- A patch release (`0.1.1`) fixes behavior or documentation without intentionally breaking a
  supported public CLI, import, configuration, conformance contract, or durable format.
- A minor release (`0.2.0`) may add capabilities and is required for an intentional breaking
  change to one of those surfaces. Its release notes must name the break, migration path, and
  affected versions.
- `1.0.0` requires an explicit architecture decision and a stronger long-term compatibility
  commitment; it is not created by routine feature work.
- Prereleases use PEP 440 alpha, beta, or release-candidate identifiers in package metadata and a
  matching Git tag such as `v0.2.0rc1`. They are not the supported channel.

The existing proof-bundle schemas and conformance API have their own compatibility rules. See
[`PROOF_BUNDLES.md`](PROOF_BUNDLES.md), [`CONFORMANCE.md`](CONFORMANCE.md), and
[`CONFORMANCE_VERSIONING.md`](CONFORMANCE_VERSIONING.md); a Tarkka version bump does not silently
change those promises.

## Release contents

Each GitHub Release contains:

- the immutable Git tag and linked commit;
- a source distribution and universal wheel built from that commit;
- a `SHA256SUMS` file covering both artifacts;
- concise release notes with user-visible changes, compatibility/migration notes, known limits,
  and links to the canonical issues and pull requests;
- the exact validation result and the GitHub Actions run that built or verified the artifacts.

Users may download the wheel from a GitHub Release and install it locally with
`python -m pip install ./tarkka-<version>-py3-none-any.whl`. This is an installation option, not a
claim that `pip install tarkka` works from PyPI.

Release notes are committed before tagging at `docs/releases/v<version>.md`. The tag-driven
workflow refuses to publish a GitHub Release without that exact file, so reviewable notes exist
alongside the source they describe.

## Release checklist

Before creating a stable release, the maintainer must:

1. Confirm the target is a clean, reviewed `main` commit and its canonical issues/PRs explain the
   included scope.
2. Set the intended version in `pyproject.toml`, update release notes, and document any public,
   compatibility, migration, or security impact.
3. Run the current deterministic validation gate:

   ```bash
   uv sync --frozen --group dev --extra mcp
   uv run --no-sync ruff check .
   uv run --no-sync mypy
   uv run --no-sync sqlfluff lint migrations
   uv run --no-sync pytest -m "not external"
   uv build --out-dir dist
   ```

4. Verify the built wheel in a clean environment, including `tarkka --help`, the five-minute
   proof/replay walkthrough, and `tarkka bundle verify` against its checked-in fixture.
5. Confirm that generated artifacts contain only intended package files and no secrets, local
   state, research content, or build-machine paths.
6. Create an annotated tag matching the package version, push it, build the release artifacts
   from that exact tag, generate `SHA256SUMS`, and publish the GitHub Release.
7. Record the release URL, tag commit, artifact checksums, validation run, and any known issues in
   the GitHub Release notes. If an artifact or tag is wrong, withdraw the release and publish a new
   corrected version rather than overwriting it.

Maintainers may additionally sign tags and artifacts when their key-management process is ready;
signature verification is not yet a release prerequisite.

## What comes next

This policy comes before automation. A follow-up may add tag-driven build and GitHub Release
automation only after this checklist has been exercised for a first release. A separate decision
is required before enabling PyPI trusted publishing or treating PyPI as a supported channel.
