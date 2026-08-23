# AI Review Automation

Tarkka uses multiple independent review signals. Automated reviewers provide evidence and suggestions; they do not override repository architecture, tests, or human judgment.

## Current roles

- CodeRabbit: broad PR review and maintainability feedback.
- KiloCode: independent review and bounded fix delegation.
- Greptile: repository-context review while free credits are available.
- GitHub Copilot review: optional GitHub-native reviewer when available.
- PR-Agent: quota-independent open-source reviewer backed by an OpenAI-compatible gateway.
- Ruff, mypy, pytest, coverage, Docling CI, and future CodeQL/security checks remain objective gates.

## Free-model policy

Repository-managed AI review automation must use explicitly free model identifiers. Do not configure a paid or ambiguous model ID and assume provider routing will keep usage free.

- OpenRouter primary: `openrouter/nvidia/nemotron-3-ultra-550b-a55b:free`
- OpenRouter fallback: disabled; PR-Agent fails closed rather than silently changing reviewer models.
- OpenCode Zen integrations, when enabled, must use model IDs ending in `-free`, such as `deepseek-v4-flash-free` or `nemotron-3-ultra-free`.

When a provider removes, renames, or temporarily disables the configured free model, fail closed. Do not silently cross over to another model or paid inference without an explicit reviewed configuration change.

## PR-Agent

The workflow in `.github/workflows/pr-agent.yml` runs PR-Agent `0.41.0-github_action` using OpenRouter. The immutable release tag is used rather than a rolling `main` or `latest` tag.

The primary model is configured in `.pr_agent.toml` as:

```text
openrouter/nvidia/nemotron-3-ultra-550b-a55b:free
```

Fallback models are intentionally disabled:

```text
[]
```

This keeps Nemotron Ultra authoritative for repository-managed PR-Agent reviews. If that endpoint is unavailable, the review should fail visibly instead of silently downgrading to a different model.

### Required secret

Create this repository Actions secret:

```text
OPENROUTER_API_KEY
```

Path in GitHub:

```text
Settings -> Secrets and variables -> Actions -> New repository secret
```

If the secret is absent, the workflow exits successfully after reporting that PR-Agent is disabled.

### Security model

PR-Agent obtains PR content through the GitHub API and does not checkout pull-request code in this secret-bearing workflow. Keep that property unless a reviewed security design requires otherwise.

Do not switch this workflow to `pull_request_target` plus an untrusted checkout. Do not expose model-provider keys to code from forked pull requests.

## Full coding agents

Google Jules and OpenHands are different from PR-Agent. They can perform implementation work rather than only reviewing diffs.

Use them selectively for bounded tasks such as investigating a failing PR, implementing an approved issue, or producing a proposed patch. They should not replace deterministic CI.

A self-hosted OpenHands deployment should run in an isolated VM/container environment with scoped GitHub/model credentials. Do not run a network-triggered coding agent directly on a general-purpose server host with unrestricted filesystem credentials.

## Review policy

For material PRs:

1. Run deterministic CI.
2. Collect independent AI reviews.
3. Validate each finding against current code, tests, and architecture.
4. Fix valid findings and add regression/contract/property tests where appropriate.
5. Do not change code merely to satisfy an automated reviewer.
6. Do not merge until CI is green and substantive findings are resolved or explicitly rejected with rationale.
