# Cobenian/.github — shared CI/CD & community health

This is the org-special **`Cobenian/.github`** repo — the single source of truth
that all Cobenian repos inherit from, implementing [`STANDARDS.md`](STANDARDS.md) §9.

## Standards

The canonical, org-wide normative docs (RFC 2119). Every product cites these.

| Doc | Governs |
|---|---|
| [`STANDARDS.md`](STANDARDS.md) | How repos are built and shipped (GitHub, CI, CD) |
| [`PLATFORM-ADOPTION.md`](PLATFORM-ADOPTION.md) | How a product **consumes** the platform (inbound: product → Accounts/Foundry/Data) |
| [`PRODUCT-SURFACE.md`](PRODUCT-SURFACE.md) | How a product **exposes** itself (outbound: REST, MCP, OAuth2 — caller → product) |
| [`IN-APP-ADMIN.md`](IN-APP-ADMIN.md) | The in-app admin surface each product owns (tier 3 of 3) |

## Layout

```
.github/
  workflows/
    elixir-ci.yml          # REUSABLE CI (workflow_call) — the heavy lifting
    fly-deploy.yml         # REUSABLE deploy (workflow_call) — retry + --wait-timeout + smoke
  PULL_REQUEST_TEMPLATE.md # org-default PR template (inherited)
  ISSUE_TEMPLATE/
    bug_report.md          # org-default (inherited)
    feature_request.md     # org-default (inherited)
templates/                 # COPY these into each consumer repo (not inherited)
  ci.yml                   # thin caller of the reusable CI
  fly-deploy.yml           # thin caller of the reusable deploy (workflow_run trigger + app inputs)
  dependabot-app.yml       # → .github/dependabot.yml  (apps)
  dependabot-library.yml   # → .github/dependabot.yml  (libraries)
  CODEOWNERS               # → .github/CODEOWNERS       (not inheritable)
```

### Inherited automatically (org defaults)
`PULL_REQUEST_TEMPLATE.md` and `ISSUE_TEMPLATE/*` apply to any repo that doesn't
define its own — no per-repo copy needed.

### Reusable, referenced by tag
`elixir-ci.yml` (CI) and `fly-deploy.yml` (deploy) are consumed via
`uses: Cobenian/.github/.github/workflows/<name>@v1`. Tag releases (`v1`, `v1.1`,
…) so consumers pin and bump deliberately; `v1` is the moving major pointer.
Deploy inputs are documented in [`STANDARDS.md`](STANDARDS.md) §4.

### Must be copied per repo (NOT inheritable)
`ci.yml`, `fly-deploy.yml` (both **thin callers** now), `dependabot.yml`, `CODEOWNERS`.

## Consuming the CI in a repo

`.github/workflows/ci.yml` (from `templates/ci.yml`):

```yaml
name: CI
on:
  push: { branches: [main] }
  pull_request: { branches: [main] }
permissions: { contents: read }
jobs:
  build-and-test:
    uses: Cobenian/.github/.github/workflows/elixir-ci.yml@v1
    with:
      profile: app          # app | library
      umbrella: false       # true for Companion
      postgres: true        # false for DB-less libraries
      nonblocking: ""        # e.g. "credo,dialyzer" while ratcheting a live repo
    secrets: inherit
```

### Reusable CI inputs

| Input | Default | Notes |
|---|---|---|
| `profile` | — (required) | `app` \| `library`; `library` skips Sobelow |
| `umbrella` | `false` | set `sobelow_root` / `migrations_path` to the child app paths |
| `postgres` | `true` | starts Postgres + runs `ecto.create/migrate`; `false` for DB-less libraries |
| `nonblocking` | `""` | comma list → those checks run report-only. Recognized: `credo`, `sobelow`, `hex_audit`, `deps_audit` |
| `dialyzer_blocking` | `false` | Dialyzer is report-only by default; flip to `true` once PLTs are stable |
| `sobelow_root` | `.` | `apps/<web_app>` for umbrellas |
| `migrations_path` | `priv/repo/migrations` | duplicate-timestamp check target |
| `elixir-version` | `1.20.0` | |
| `otp-version` | `29.0.1` | |
| `postgres_image` | `postgres:17` | |
| `gitleaks_version` | `8.21.2` | CLI binary (the action needs a paid org license) |

## ⚠️ Branch-protection check name

Because CI is a **reusable** workflow, the status-check context is **nested**:
`build-and-test / Build and test` (not bare `Build and test`). Set branch
protection's required `context` to that nested string. Verify with:

```bash
gh api repos/Cobenian/<repo>/commits/<sha>/check-runs --jq '.check_runs[].name'
```

The deploy trigger keys off the workflow **name** (`CI`), which is unaffected.

## CI security-posture artifact → Foundry / Panel

After the build, the reusable CI re-runs the Elixir scanners in machine-readable mode,
folds their results into **one JSON file**, and uploads it as the workflow-run artifact
**`cobenian-scan-posture`**. Foundry's GitHub connector reads that artifact off the
completed run and emits `connectors.scan_result.received` so **Cobenian Panel's app &
security monitor** can fold CI-computed posture per repo + commit (issue
[#106](https://github.com/Cobenian/cobenian-foundry/issues/106) **Option A**;
cobenian-foundry SPEC-CON-003 §14).

- **No configuration, no secret, no endpoint.** The connector pulls the artifact via the
  GitHub App install it already has — CI needs no `FOUNDRY_INGEST_TOKEN` and makes no
  network call to Foundry. (This replaces the reverted POST-with-bearer emitter,
  PR #11 → reverted by #12; only the *transport* changed.)
- **Always-on & never a gate.** The build/upload steps are `continue-on-error: true` +
  `if: always()` and internally guarded, so they can **never** fail a caller's build and
  still run when an earlier blocking scanner failed. The existing blocking scanner steps
  are unchanged and still own pass/fail.
- **Artifact contract** — the single JSON file's body:

  ```jsonc
  { "source": "github",                        // links to the repo/workflow_run events
    "repo": "<owner>/<repo>", "head_sha": "…", "run_url": "…",
    "workflow_run_id": "…", "scanned_at": "<ISO8601>",
    "sobelow":      { "findings": N, "by_confidence": { "high": N, "medium": N, "low": N } },
    "mix_audit":    [ { "package": "…", "id": "CVE/GHSA", "severity": "…", "title": "…" } ],
    "hex_audit":    [ { "package": "…", "version": "…", "reason": "…" } ],
    "gitleaks":     { "secrets_found": N },     // COUNT ONLY — never a value or location
    "hex_outdated": [ { "package": "…", "current": "…", "latest": "…" } ] }
  ```

  A scanner that did not run or failed is **omitted** — never fabricated as clean. Per
  cobenian-foundry **CON-GH-015**, no secret values, secret locations, or source snippets
  are ever emitted (gitleaks/Sobelow contribute counts only); the raw scanner reports stay
  on the runner and are never uploaded.

## Per-repo profile cheat-sheet

| Repo | profile | umbrella | postgres | deploy |
|---|---|---|---|---|
| cobenian-accounts | app | false | true | yes |
| cobenian-cadence | app | false | true | yes |
| cobenian-agents (Oversight) | app | false | true | yes |
| cobenian_companion_umbrella | app | true | true | yes |
| cobenian-core-accounts | library | false | false | no |
