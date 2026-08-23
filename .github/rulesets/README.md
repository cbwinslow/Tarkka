# Repository Rulesets

`main-protection.json` is an importable GitHub repository ruleset for Tarkka's default branch.

## Import

1. Open repository **Settings**.
2. Go to **Rules -> Rulesets**.
3. Select **New ruleset -> Import a ruleset**.
4. Upload `.github/rulesets/main-protection.json`.
5. Review the imported settings and create the ruleset.

The ruleset requires pull requests, resolution of review threads, and deterministic checks that run on every pull request:

- `Quality`
- `Tests (Python 3.11)`
- `Tests (Python 3.12)`
- `Tests (Python 3.13)`
- `Review dependency changes`

It also requires the PR branch to be up to date before merge and blocks branch deletion and force pushes.

Docling and package validation are intentionally not required statuses because those workflows are path-filtered and do not run on every pull request. AI reviewers are intentionally advisory rather than required merge gates so provider outages or model availability cannot block deterministic development. CodeQL remains managed by GitHub's repository-level default setup rather than a duplicate advanced workflow.

Updating this JSON file does not mutate an already-created GitHub ruleset automatically. After changing required checks here, update the live repository ruleset in **Settings -> Rules -> Rulesets** or re-import the reference configuration.

## pre-commit

Tarkka includes `.pre-commit-config.yaml` for fast local hygiene checks, including standard file-format checks, Ruff, and SQLFluff. The canonical development environment and tool versions remain declared through `uv`/`pyproject.toml`, and GitHub Actions remain the authoritative merge gates.

If the `pre-commit.ci` GitHub app is enabled for this repository, treat it as supplementary automation rather than a required merge check unless the repository ruleset is deliberately changed to require it.
