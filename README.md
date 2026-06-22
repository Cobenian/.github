# Cobenian/.github — shared CI/CD & community health

This is the org-special **`Cobenian/.github`** repo — the single source of truth
that all Cobenian repos inherit from, implementing [`STANDARDS.md`](STANDARDS.md) §9.

## Layout

```
.github/
  workflows/
    elixir-ci.yml          # REUSABLE CI (workflow_call) — the heavy lifting
  PULL_REQUEST_TEMPLATE.md # org-default PR template (inherited)
  ISSUE_TEMPLATE/
    bug_report.md          # org-default (inherited)
    feature_request.md     # org-default (inherited)
templates/                 # COPY these into each consumer repo (not inherited)
  ci.yml                   # thin caller of the reusable CI
  fly-deploy.yml           # app deploy (per-repo: workflow_run trigger + app domain)
  dependabot-app.yml       # → .github/dependabot.yml  (apps)
  dependabot-library.yml   # → .github/dependabot.yml  (libraries)
  CODEOWNERS               # → .github/CODEOWNERS       (not inheritable)
```

### Inherited automatically (org defaults)
`PULL_REQUEST_TEMPLATE.md` and `ISSUE_TEMPLATE/*` apply to any repo that doesn't
define its own — no per-repo copy needed.

### Reusable, referenced by tag
`elixir-ci.yml` is consumed via
`uses: Cobenian/.github/.github/workflows/elixir-ci.yml@v1`. Tag releases (`v1`,
`v1.1`, …) so consumers pin and bump deliberately.

### Must be copied per repo (NOT inheritable)
`ci.yml`, `fly-deploy.yml`, `dependabot.yml`, `CODEOWNERS`.

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

## Per-repo profile cheat-sheet

| Repo | profile | umbrella | postgres | deploy |
|---|---|---|---|---|
| cobenian-accounts | app | false | true | yes |
| cobenian-cadence | app | false | true | yes |
| cobenian-agents (Oversight) | app | false | true | yes |
| cobenian_companion_umbrella | app | true | true | yes |
| cobenian-core-accounts | library | false | false | no |
