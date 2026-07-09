# Cobenian/.github — shared CI/CD & community health

This is the org-special **`Cobenian/.github`** repo — the single source of truth
that all Cobenian repos inherit from, implementing [`STANDARDS.md`](STANDARDS.md) §9.

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
| `foundry_events_url` | `https://console.cobenian.com/api/events` | Foundry inbound event ingest endpoint for the CI security-posture event (below). Only used when `FOUNDRY_INGEST_TOKEN` is set |

### CI security-posture event (opt-in) → Foundry / Panel

The reusable CI can emit a **CI-computed security & freshness posture** event to
Foundry so **Cobenian Panel's app & security monitor** can fold it per repo + commit
(tracked as **PANEL-SEC-042**). It is **opt-in and fully non-blocking**:

- **Secret:** set `FOUNDRY_INGEST_TOKEN` on the repo (a workspace-scoped Foundry/Accounts
  bearer, `aud: cobenian-foundry`) and it flows through the existing `secrets: inherit`.
  **No token → the step is a no-op**; nothing else changes and no CI time is added.
- **What it does:** after the build, it re-runs Sobelow, `mix deps.audit` (mix_audit),
  `mix hex.audit`, gitleaks, and `mix hex.outdated` in machine-readable mode, folds their
  results into one JSON payload, and `POST`s it to `foundry_events_url`.
- **Never a gate:** the emit step is `continue-on-error: true` and internally guarded, so
  it can **never** fail a caller's build. The existing blocking scanner steps are unchanged.
- **Event contract** (POST body → Foundry `POST /api/events`):

  ```jsonc
  { "name": "connectors.scan_result.received",   // Panel folds by payload.source
    "subject": "repo:<owner>/<repo>",
    "payload": {
      "source": "github",                        // links to the repo/workflow_run events
      "repo": "<owner>/<repo>", "head_sha": "…", "run_url": "…",
      "workflow_run_id": "…", "scanned_at": "<ISO8601>",
      "sobelow":      { "findings": N, "by_confidence": { "high": N, "medium": N, "low": N } },
      "mix_audit":    [ { "package": "…", "id": "CVE/GHSA", "severity": "…", "title": "…" } ],
      "hex_audit":    [ { "package": "…", "version": "…", "reason": "…" } ],
      "gitleaks":     { "secrets_found": N },     // COUNT ONLY — never a value or location
      "hex_outdated": [ { "package": "…", "current": "…", "latest": "…" } ]
    } }
  ```

  A scanner that did not run or failed is **omitted** (null) — never fabricated as clean.
  Per cobenian-foundry **CON-GH-015**, no secret values, secret locations, or source
  snippets are ever emitted (gitleaks/Sobelow contribute counts only).

> **Foundry-side confirmation needed.** `connectors.scan_result.received` is a **new**
> connector resource name (not one of SPEC-CON-003 §6's five) and CI emits it via the
> generic authenticated `POST /api/events` surface rather than the connector's own
> ingest. If Foundry prefers a dedicated ingest route/HMAC or a different name/source,
> adjust `foundry_events_url` + the emit step and tell Panel so its fold stays aligned.

## ⚠️ Branch-protection check name

Because CI is a **reusable** workflow, the status-check context is **nested**:
`build-and-test / Build and test` (not bare `Build and test`). Set branch
protection's required `context` to that nested string. Verify with:

```bash
gh api repos/Cobenian/<repo>/commits/<sha>/check-runs --jq '.check_runs[].name'
```

The deploy trigger keys off the workflow **name** (`CI`), which is unaffected.

## Per-repo profile cheat-sheet

| Repo | profile | umbrella | postgres | deploy |
|---|---|---|---|---|
| cobenian-accounts | app | false | true | yes |
| cobenian-cadence | app | false | true | yes |
| cobenian-agents (Oversight) | app | false | true | yes |
| cobenian_companion_umbrella | app | true | true | yes |
| cobenian-core-accounts | library | false | false | no |
