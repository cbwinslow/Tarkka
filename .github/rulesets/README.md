# Repository Rulesets

`main-protection.json` is an importable GitHub repository ruleset for Tarkka's default branch.

## Import

1. Open repository **Settings**.
2. Go to **Rules -> Rulesets**.
3. Select **New ruleset -> Import a ruleset**.
4. Upload `.github/rulesets/main-protection.json`.
5. Review the imported settings and create the ruleset.

The ruleset requires pull requests, resolution of review threads, and the deterministic CI jobs that run on every pull request:

- `Quality`
- `Tests (Python 3.11)`
- `Tests (Python 3.12)`
- `Tests (Python 3.13)`

It also requires the PR branch to be up to date before merge and blocks branch deletion and force pushes.

Docling is intentionally not a required status because its workflow is path-filtered and does not run on every pull request. AI reviewers are intentionally advisory rather than required merge gates so provider outages or free-tier availability cannot block development.

## pre-commit.ci

Tarkka does not currently use a `.pre-commit-config.yaml`. Local development tooling is managed through `uv`, and authoritative validation is performed by GitHub Actions. If the `pre-commit.ci` GitHub app remains installed for this repository it may emit an error status without providing useful validation; disable repository access for that app unless pre-commit is deliberately adopted later.
