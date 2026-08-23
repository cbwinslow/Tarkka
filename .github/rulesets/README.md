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

## pre-commit.ci

Tarkka does not currently use a `.pre-commit-config.yaml`. Local development tooling is managed through `uv`, and authoritative validation is performed by GitHub Actions. If the `pre-commit.ci` GitHub app remains installed for this repository it may emit an error status without providing useful validation; disable repository access for that app unless pre-commit is deliberately adopted later.
