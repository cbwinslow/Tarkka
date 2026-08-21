# GitHub Automation Plan

Tarkka should use GitHub automation where it removes repeatable maintenance work or strengthens deterministic quality gates. Avoid workflows that duplicate existing checks or introduce broad write permissions without clear benefit.

## Current automated gates

- core CI: Ruff, strict mypy, SQLFluff, pytest across supported Python versions, branch coverage
- Docling integration compatibility
- Dependabot for Python and GitHub Actions dependencies
- PR-Agent AI review through OpenRouter, with Nemotron Ultra as the primary model

## Next automation layers

1. Pull-request path labeling
   - documentation
   - database/migrations
   - tests
   - CI/automation
   - discovery/connectors
   - extraction/research
   - agent interfaces
   - packaging/dependencies

2. Structured issue forms
   - bug report
   - feature/request
   - architecture/design proposal
   - research/source integration
   - assign deterministic initial labels from the form rather than guessing from free text

3. Security
   - CodeQL v4 for Python
   - dependency vulnerability audit
   - secret scanning / push protection where repository settings permit

4. Package quality
   - build wheel and sdist
   - inspect package metadata
   - install wheel into a clean environment
   - smoke-test the `tarkka` CLI
   - retain build artifacts

5. Release automation
   - only after the license and public package/release policy are finalized
   - tag-driven build
   - GitHub Release artifact publication
   - optional PyPI trusted publishing

6. AI review redundancy
   - OpenRouter PR-Agent remains primary with Nemotron Ultra
   - evaluate OpenCode Zen as a second independent reviewer using its OpenAI-compatible endpoint, preferably DeepSeek V4 Flash
   - keep provider failures isolated so an optional AI reviewer cannot block deterministic CI unless explicitly promoted to a required check

## Workflow rules

- pin third-party actions to immutable commit SHAs
- use Node 24-compatible action releases
- default to read-only repository permissions
- grant write permissions per job only when required
- never checkout untrusted fork code in secret-bearing jobs
- use concurrency cancellation for superseded PR runs
- keep deterministic CI authoritative over AI review
- do not create duplicate lint/test workflows
