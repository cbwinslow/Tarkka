# GitHub Automation

Tarkka uses GitHub automation where it removes repeatable maintenance work or strengthens deterministic quality and security gates. Avoid workflows that duplicate existing checks, execute untrusted code with secrets, or introduce broad write permissions without a clear benefit.

## Current automated gates

### Core CI

- `uv` lockfile validation and frozen development-environment sync
- Ruff linting
- strict mypy type checking
- SQLFluff linting for PostgreSQL migrations
- zizmor audit of GitHub Actions configuration
- pytest across Python 3.11, 3.12, and 3.13
- branch coverage on Python 3.13
- exact 100% repository-wide statement and branch coverage for the deterministic test surface
- 100% changed-line coverage for pull requests
- retained JUnit and coverage artifacts

These deterministic checks are authoritative merge gates through the repository ruleset.

### Dependency and supply-chain automation

- Dependabot uses the native `uv` ecosystem for Python dependencies
- minor/patch dependency updates are grouped; major updates remain isolated
- GitHub Actions minor/patch updates are grouped; majors remain isolated
- dependency submission is isolated to the job that requires `contents: write`
- dependency review remains read-only and runs independently of submission success
- third-party Actions are pinned to immutable commit SHAs

### Package quality

- build wheel and source distribution
- verify expected distribution artifacts
- install the wheel into a clean environment
- independently install the source distribution into a clean environment
- smoke-test `import tarkka` and `tarkka --help` from both artifacts
- retain distributions as workflow artifacts

### Integration and security regression coverage

- real Docling integration compatibility is exercised separately from fast deterministic CI
- focused security/property regressions run on a daily schedule and can be dispatched manually
- CodeQL is intended to use GitHub repository-level default setup rather than a duplicate advanced workflow

### Pull-request and issue automation

- PR path labeling covers documentation, tests, CI/automation, packaging/dependencies, database/migrations, discovery/connectors, extraction/research, and agent/interfaces
- structured issue forms cover bugs, features, architecture/design proposals, research/source integrations, and general work
- issue forms apply deterministic initial labels instead of relying on AI classification of free text
- the PR template requires behavior/invariants, test plans, risk/failure modes, provenance/security impact, compatibility/migration impact, and review notes

### AI review

- PR-Agent through OpenRouter is the primary AI reviewer and uses Nemotron Ultra
- OpenCode Zen provides an independent advisory reviewer through its OpenAI-compatible endpoint
- the Zen reviewer checks out only the trusted base revision, never executes PR-head code in the secret-bearing job, treats PR content as untrusted prompt data, and is disabled for fork PRs
- `OPENCODE_REVIEW_MODEL` can select the Zen model without changing workflow code
- AI provider/model failures are advisory and cannot block deterministic CI

## Repository ruleset

`.github/rulesets/main-protection.json` is the reference configuration for the live default-branch ruleset. It requires:

- pull requests
- resolution of review conversations
- `Quality`
- `Tests (Python 3.11)`
- `Tests (Python 3.12)`
- `Tests (Python 3.13)`
- `Review dependency changes`
- up-to-date branches before merge
- no deletion or force-push of the protected branch

The live GitHub ruleset must be checked for drift from this reference; the checked-in JSON is not proof that native repository settings have already been applied. Track current live drift and its resolution in #192 so transient repository state has a single source of truth.

Keep path-filtered workflows such as package and Docling validation out of the global required-status list unless they are changed to report a result on every pull request.

## Remaining automation work

1. Repository security settings
   - verify CodeQL default setup is enabled for Python
   - verify secret scanning and push protection are enabled where GitHub permits them

2. Repository lifecycle settings
   - consider automatically deleting merged head branches to reduce stale-branch clutter
   - consider enabling GitHub auto-merge now that deterministic merge gates are established
   - keep branch-update behavior aligned with the ruleset's strict freshness requirement

3. Release automation
   - finalize the project license and public package/release policy first
   - then add tag-driven builds, GitHub Release artifacts, and optional PyPI trusted publishing

4. Reviewer operations
   - configure `OPENCODE_API_KEY` to activate the Zen reviewer
   - optionally set `OPENCODE_REVIEW_MODEL` when a different current Zen model is preferred
   - periodically review hosted reviewer overlap and rate limits; remove integrations that add noise without distinct findings

5. CI efficiency
   - track workflow duration and flaky/infrastructure-failure rate
   - keep fast deterministic checks on every PR
   - move genuinely expensive deterministic tests behind explicit markers only when their runtime becomes material

## Workflow rules

- pin third-party Actions to immutable commit SHAs
- use maintained action releases compatible with the current GitHub runner runtime
- default to read-only repository permissions
- grant write permissions per job only when required
- never checkout or execute untrusted fork/PR-head code in secret-bearing jobs
- bound external/model inputs and fail safely on malformed responses
- use concurrency cancellation for superseded PR runs
- keep deterministic CI authoritative over AI review
- do not create duplicate lint/test/security workflows when repository-level GitHub features provide the same capability more safely
