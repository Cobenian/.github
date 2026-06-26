# Cobenian Engineering Standards — GitHub, CI & CD

**Status:** Adopted · **Version:** 1.6 · **Last updated:** 2026-06-22

The single reference for how Cobenian repositories are structured, tested,
deployed, and governed. The goal is **consistency by default**: every repo looks
and behaves the same, so anyone can move between them without surprises.

> **Canonical home.** This file lives in **`Cobenian/.github`** — the single
> source of truth for all Cobenian repos, alongside the reusable CI workflow (§9)
> and the per-repo templates. Any copy in a product repo is a pointer to this one.
> (Consolidated from the `cobenian-cadence` and `cobenian-accounts` drafts.)

> **Platform reality (read first).** The Cobenian GitHub org is on the **Team**
> plan. **GitHub Advanced Security is NOT available.** That means CodeQL, native
> secret scanning, push protection, and `dependency-review-action` cannot be used
> on private repos. We use CI-based equivalents instead (§5) — chiefly **gitleaks**.
> CodeQL also does not support Elixir, so we would not use it regardless.

---

## 1. Repository profiles

Every repo is one of two profiles. The profile decides which parts of this
standard apply. (An **umbrella** is still the *application* profile, with the
invocation tweaks noted in §3.3.)

| | **Application** | **Library** |
|---|---|---|
| Examples | cobenian-accounts, cobenian-cadence, cobenian_companion_umbrella (umbrella) | cobenian-core-accounts |
| CI (format/compile/credo/test/dialyzer) | ✅ | ✅ |
| Postgres in CI | ✅ (if it has a Repo) | only if it has DB-backed tests |
| Sobelow (Phoenix SAST) | ✅ | ❌ (no web surface) |
| Migration checks | ✅ (if it has migrations) | ❌ |
| `/health` endpoint | ✅ | ❌ |
| CD to Fly | ✅ | ❌ |
| Hex publish workflow | ❌ | optional (on tags) |
| Dependabot, gitleaks, mix_audit, hex.audit | ✅ | ✅ |
| Branch protection + governance files | ✅ | ✅ |

---

## 2. Branching & pull-request model

- **`main` is always deployable.** No direct pushes — everything goes through a PR.
- **Short-lived branches:** `pipeline/<YYYY-MM-DD>-<slug>` for pipeline work,
  otherwise `feat/<slug>`, `fix/<slug>`, `chore/<slug>`.
- **Linear history.** Merge via **squash only**; no merge commits. Head branches
  auto-delete on merge.
- **Self-merge is allowed** once CI is green. With a small team on the Team plan we
  do **not** require a second approving review (you cannot approve your own PR, so
  requiring it would block solo work). `CODEOWNERS` auto-requests review as a
  courtesy, not a gate.
- **Conventional Commits** as a style convention for messages
  (`feat:`, `fix:`, `chore:`, `docs:`, …). Not enforced by a bot.

---

## 3. CI — `.github/workflows/ci.yml`

Runs on every PR and on push to `main`. The job **must** be named `Build and test`
inside a workflow named `CI` — the deploy workflow (§4) keys off both names, and
branch protection (§7) requires the `Build and test` check.

**Standard toolchain pins (all repos):**

| Thing | Pin |
|---|---|
| Elixir | `1.20.0` |
| OTP | `29.0.1` |
| Postgres service | `postgres:17` |
| `actions/checkout` | `v7` |
| `actions/cache` | `v5` |
| `erlef/setup-beam` | `v1` |

`.tool-versions` is the single source of truth for the language pins (`erlang
29.0.1`, `elixir 1.20.0`, `postgres 17.4`); CI mirrors it. Let Dependabot keep the
action versions current.

**Pipeline (order matters — cheapest/most-common failures first):**

```
checkout
→ [duplicate-migration check]        # apps with migrations (see §3.1)
→ setup-beam (Elixir/OTP pins)
→ cache deps + _build (key: mix.lock)
→ mix deps.get
→ mix deps.unlock --check-unused     # lockfile hygiene (blocking)
→ mix format --check-formatted       # blocking — CHECK variant (must fail, not auto-fix)
→ mix compile --warnings-as-errors   # blocking
→ mix credo --strict                 # blocking
→ mix sobelow --exit                 # blocking — APPS ONLY
→ mix hex.audit                      # blocking — retired packages
→ mix deps.audit                     # blocking — Hex CVEs (mix_audit)
→ mix ecto.create && mix ecto.migrate  # if the repo has a Repo
→ mix test                           # blocking
→ mix dialyzer (cached PLTs)         # NON-blocking initially, then promote
→ gitleaks                           # blocking — secret scanning (all repos)
```

> **Local convenience.** A `precommit` mix alias may mirror this gate but
> **auto-fixes** (`format`, `deps.unlock --unused`) for developers. **CI must use
> the check variants** (`--check-formatted`, `--check-unused`) so it *fails* rather
> than silently fixing. (A CI driven from a mutating `precommit` alias has a hole
> where unformatted code can merge — use the explicit check steps below. All repos
> now call the reusable workflow, which already uses the check variants.)

**Reference `ci.yml` (application profile):**

```yaml
name: CI

on:
  push:
    branches: [main]
  pull_request:
    branches: [main]

permissions:
  contents: read

jobs:
  test:
    name: Build and test
    runs-on: ubuntu-latest
    env:
      MIX_ENV: test
    services:
      db:
        image: postgres:17
        env:
          POSTGRES_USER: postgres
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: postgres
        ports: ["5432:5432"]
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 10s --health-timeout 5s --health-retries 5
    steps:
      - uses: actions/checkout@v7

      # Apps with hand-written migrations: fail fast on duplicate timestamps.
      - name: Check for duplicate migration versions
        run: |
          dupes=$(ls priv/repo/migrations 2>/dev/null \
            | grep -E '^[0-9]+_' | sed -E 's/_.*//' | sort | uniq -d)
          if [ -n "$dupes" ]; then
            echo "::error::Duplicate migration version(s): $dupes"; exit 1
          fi
          echo "No duplicate migration versions."

      - uses: erlef/setup-beam@v1
        with:
          elixir-version: "1.20.0"
          otp-version: "29.0.1"

      - name: Cache deps and _build
        uses: actions/cache@v5
        with:
          path: |
            deps
            _build
          key: ${{ runner.os }}-mix-${{ hashFiles('**/mix.lock') }}
          restore-keys: ${{ runner.os }}-mix-

      - run: mix deps.get
      - run: mix deps.unlock --check-unused
      - run: mix format --check-formatted
      - run: mix compile --warnings-as-errors
      - run: mix credo --strict
      - run: mix sobelow --exit          # remove for library profile
      - run: mix hex.audit
      - run: mix deps.audit
      - run: mix ecto.create --quiet && mix ecto.migrate --quiet
      - run: mix test

      - name: Cache Dialyzer PLTs
        uses: actions/cache@v5
        with:
          path: priv/plts
          key: ${{ runner.os }}-plt-v2-${{ hashFiles('**/mix.lock') }}
          restore-keys: ${{ runner.os }}-plt-v2-
      - name: Dialyzer
        run: mix dialyzer --format github
        continue-on-error: true          # promote to blocking once PLTs are stable

      # gitleaks via the CLI binary. The gitleaks-ACTION requires a PAID license
      # for organization accounts (Cobenian is an org), so it would fail; the
      # binary is free. Pin the version and bump deliberately.
      - name: gitleaks (secret scan)
        run: |
          VERSION=8.21.2
          curl -sSfL "https://github.com/gitleaks/gitleaks/releases/download/v${VERSION}/gitleaks_${VERSION}_linux_x64.tar.gz" \
            | tar -xz gitleaks
          ./gitleaks detect --source . --redact --no-banner --exit-code 1
```

**Required `mix.exs` dev/test deps** (so the gates above exist):
`credo`, `sobelow` (apps), `mix_audit`, `dialyxir`, and (optional) `excoveralls`.

### 3.1 Duplicate-migration check
Two PRs merged the same day can pick the same migration timestamp, which only
breaks `mix ecto.migrate` (and the Fly release command) once both land on `main`.
The PR-time check above keeps it a cheap fix. Apps with migrations **must** include
it. *(Optional enhancement: `excellent_migrations` to also flag unsafe migration
operations — introduce non-blocking, diff-scoped to changed files, since it is noisy
over large legacy migration histories.)*

### 3.2 Coverage (optional, non-blocking)
Add `excoveralls` and report coverage; do **not** gate a percentage early. Promote
to a threshold once the codebase is substantial.

### 3.3 Umbrella specifics (e.g. Companion)
- **Tests** run across child apps (`mix test` at the umbrella root, which fans out;
  the root `mix.exs` may alias `setup`/`test` to `cmd mix …`).
- **Sobelow** must scan the web app (`apps/<web_app>`) — run it umbrella-aware
  (`mix sobelow --root apps/<web_app>` or per-app) rather than at the bare root.
- **Dialyzer** PLTs are built umbrella-wide; cache `_build` accordingly.
- **Migrations** live in the domain app (e.g. `apps/cobenian_companion`); point the
  duplicate-migration check at that path.

---

## 4. CD — `.github/workflows/fly-deploy.yml` (applications only)

Deploy is **gated on a successful CI run**, not on the merge alone. It triggers on
the **CI** workflow completing successfully on `main`, and deploys the **exact SHA
CI validated**. A failing build therefore stops the deploy itself.

> **Why a separate `workflow_run` file, not an in-workflow `deploy` job?** An
> in-workflow `deploy` job (`needs: test`, push-to-main) also works (Oversight used
> to do this). We standardize on the separate `workflow_run` file because it deploys
> the exact validated SHA, keeps deploy concerns out of the PR-time workflow, and
> makes the gate explicit. Every app uses this pattern via the thin caller below.

The deploy **steps live in a reusable workflow** in `Cobenian/.github`
(`.github/workflows/fly-deploy.yml`, `workflow_call`), so deploy hardening is a
one-edit change for every app. Each app keeps a **thin caller** that owns only what
must be local — the `workflow_run` trigger and the main-branch gate — and passes
per-app inputs (mirrors how CI is split: thin `ci.yml` → `elixir-ci.yml@v1`):

```yaml
name: Fly Deploy
on:
  workflow_run:
    workflows: ["CI"]
    types: [completed]
permissions:
  contents: read

jobs:
  deploy:
    # Only a *successful* CI run on `main` deploys.
    if: >-
      github.event.workflow_run.conclusion == 'success' &&
      github.event.workflow_run.head_branch == 'main'
    uses: Cobenian/.github/.github/workflows/fly-deploy.yml@v1
    with:
      head_sha: ${{ github.event.workflow_run.head_sha }}
      app_domain: <app-domain>   # e.g. accounts.cobenian.com
      # ready_path: /readyz      # optional readiness smoke check
      # uses_hex_org_key: true   # repos that fetch private Hex deps
    secrets: inherit
```

### Reusable deploy inputs

| Input | Default | Notes |
|---|---|---|
| `head_sha` | — (required) | exact SHA CI validated; the deploy checks this out |
| `app_domain` | — (required) | host for the post-deploy smoke test |
| `health_path` | `/health` | liveness path curled after deploy |
| `ready_path` | `""` | optional readiness path (e.g. `/readyz`); skipped when empty |
| `uses_hex_org_key` | `false` | pass the private Cobenian Hex org key as a BuildKit build secret |

Secrets `FLY_API_TOKEN` (required) and `HEX_ORG_KEY` (optional) flow through
`secrets: inherit`. Like the reusable CI, the deploy workflow is pinned by tag
(`@v1`); bump deliberately.

**Migrations on deploy:** run via the Fly **release command** (`mix ecto.migrate`
in the release), configured in `fly.toml` / the release module — not in the
workflow.

**Transient release-machine flakes:** the `release_command` machine occasionally
fails or hangs on cold start (Fly host scheduling, or a Postgres cold-connect),
aborting an otherwise-good deploy with errors like `internal: process not found`,
`machine failed to start`, or `deadline_exceeded: machine still starting`. The
reusable deploy step therefore **retries once** and passes `--wait-timeout 15m` to
ride out a slow cold start; this is safe because the release command is idempotent
(already-applied migrations skip). A genuinely broken migration still fails after
the second attempt. For a persistent platform blip, the fallback is a manual rerun
of the Fly Deploy workflow (`gh run rerun <id> --failed`), spacing reruns a few
minutes apart so Fly's host pool can recover.

**Deploy bootstrap (one-time, manual — see §6):** the first deploy is done locally
by a human (`fly launch` is interactive and creates the app). The workflow handles
every subsequent merge.

**Library release (optional):** libraries have no Fly deploy. If published, a
`release.yml` triggers on tag `v*` to build docs + (later) publish to the Hex
private organization. Distribution starts as a git dependency, so initially this is
just tag + release notes.

---

## 5. Security & dependency automation

Because there is no GitHub Advanced Security on the Team plan, security lives in CI
and Dependabot:

| Concern | Tool | Where |
|---|---|---|
| Secret scanning | **gitleaks** (CLI binary, not the action) | CI job (all repos) + optional pre-commit hook |
| Phoenix SAST | **Sobelow** | CI (apps) |
| Hex CVEs | **mix_audit** (`mix deps.audit`) | CI (all) |
| Retired packages | **mix hex.audit** | CI (all) |
| Dependency updates | **Dependabot** | `.github/dependabot.yml` (all) |
| Vulnerability alerts | **Dependabot alerts + security updates** | repo setting (all) |

> **gitleaks licensing:** use the **gitleaks CLI binary** (see §3 reference
> workflow), not `gitleaks/gitleaks-action@v2` — the action requires a paid license
> for organization accounts. The binary is free and pinned by version.

**`.github/dependabot.yml`:**

```yaml
version: 2
updates:
  - package-ecosystem: mix
    directory: "/"
    schedule: { interval: weekly }
    groups:
      mix-deps: { patterns: ["*"] }
  - package-ecosystem: github-actions
    directory: "/"
    schedule: { interval: weekly }
    groups:
      actions: { patterns: ["*"] }
  - package-ecosystem: docker        # apps with a Dockerfile
    directory: "/"
    schedule: { interval: weekly }
  - package-ecosystem: npm           # ONLY if the repo has assets/package.json
    directory: "/assets"
    schedule: { interval: weekly }
    groups:
      js-deps: { patterns: ["*"] }
```

> **Audit note:** no current repo has an `assets/package.json` (esbuild/tailwind are
> mix-managed), so the **npm** block is omitted until JS deps actually appear.

---

## 6. Secrets

- **Never** commit secrets. gitleaks (§5) is the backstop.
- Runtime config reads env vars in `config/runtime.exs`; the repo references secret
  **names** only.
- **Fly:** `fly secrets set NAME=value`. Common names across apps:
  `SECRET_KEY_BASE`, `DATABASE_URL` (set by Fly), plus per-app integrations
  (`WORKOS_*`, `STRIPE_*`, `JWT_SIGNING_KEY`, `EMAIL_API_KEY`, …).
- **GitHub Actions:** the only required secret is `FLY_API_TOKEN`
  (`fly tokens create deploy`), added under repo → Settings → Secrets.

---

## 7. Branch protection & repo settings

Identical across all repos. Apply via `gh api` **after** the CI workflow exists (so
there is a check to require):

```bash
REPO=Cobenian/<repo>
gh api -X PUT "repos/$REPO/branches/main/protection" \
  --input - <<'JSON'
{
  "required_status_checks": {
    "strict": true,
    "checks": [{ "context": "Build and test" }]
  },
  "enforce_admins": false,
  "required_pull_request_reviews": { "required_approving_review_count": 0 },
  "required_linear_history": true,
  "allow_force_pushes": false,
  "allow_deletions": false,
  "restrictions": null
}
JSON

# Squash-only + auto-delete merged branches
gh api -X PATCH "repos/$REPO" \
  -F allow_merge_commit=false -F allow_rebase_merge=false \
  -F allow_squash_merge=true  -F delete_branch_on_merge=true

# Dependabot security updates (free on Team)
gh api -X PUT "repos/$REPO/automated-security-fixes"
gh api -X PUT "repos/$REPO/vulnerability-alerts"
```

Settings summary: require status check **Build and test**, **strict** (branch must
be up to date), **linear history**, **no force-push**, **no deletions**, **0
required reviews**, **squash-merge only**, **auto-delete** head branches,
**Dependabot alerts + security updates on**.

---

## 8. Governance & repo files

Every repo contains:

- `README.md` — what it is, how to run it locally.
- `CLAUDE.md` — conventions (thin LiveViews, logic in contexts, search-before-
  create, `mix format` + `--warnings-as-errors` clean, Oban/Req/Joken, brand/
  theming). See the Cobenian Elixir standards.
- `ARCHITECTURE.md` — context/module map and external boundaries.
- `.github/CODEOWNERS` — default owner.
- `.github/pull_request_template.md` and issue templates.
- `CONTRIBUTING.md` — branching, Conventional Commits, how CI/CD works (links here).
- `.gitignore` (incl. `erl_crash.dump`, `priv/plts`), `.formatter.exs`,
  `.credo.exs` (shared config), `.sobelow-conf` (apps).

---

## 9. Keeping repos consistent (the mechanism)

Copy-pasted workflows drift. The durable fix is **one source of truth**:

1. Create an org **`.github` repo** (or use `cobenian-claude-skills`) hosting a
   **reusable workflow** (`on: workflow_call`) — e.g. `.github/workflows/elixir-ci.yml`.
2. Each repo's `ci.yml` becomes a thin caller:

   ```yaml
   name: CI
   on:
     push: { branches: [main] }
     pull_request:   # any base branch, so stacked PRs are CI-verified
   jobs:
     build-and-test:
       uses: Cobenian/.github/.github/workflows/elixir-ci.yml@v1
       with:
         profile: app             # app | library (required)
         umbrella: false          # true for Companion
         postgres: true           # false for DB-less libraries
         nonblocking: ""           # report-only checks while ratcheting (see §10)
         dialyzer_blocking: false # Dialyzer report-only by default; flip when stable
       secrets: inherit
   ```

   Recognized `nonblocking` checks: `credo`, `sobelow`, `hex_audit`, `deps_audit`.
   Dialyzer is governed separately by `dialyzer_blocking` (report-only by default).

3. Update the standard once; every repo inherits it. Pin a tag (`@v1`) and bump
   deliberately.
4. The org `.github` repo also provides **default** community-health files
   (PR/issue templates) for repos that lack their own. (Note: `CODEOWNERS` and
   `dependabot.yml` are **not** inheritable — copy them per repo from `templates/`.)

> **Required-check naming caveat.** When CI is a *reusable* workflow invoked via
> `uses:`, the status-check context is **nested** (e.g. `build-and-test / Build and
> test`), not the bare `Build and test`. So when you build the reusable workflow,
> update the branch-protection `context` in §7 to the nested name (verify with
> `gh api repos/$REPO/commits/<sha>/check-runs`). The deploy trigger keys off the
> workflow *name* (`CI`), which is unaffected.

> Building this reusable workflow is a recommended follow-up. Until it exists, copy
> the references in §3–§5 verbatim.

---

## 10. Per-repo audit & safe rollout (the ratchet)

**Rollout is complete** — all five repos call the reusable workflow (`@v1`) and
every ratchet has been promoted to blocking. This table is kept as the historical
record of what each repo started from and how it was brought clean; the `nonblocking`
ratchet remains the playbook for any future live-app onboarding.

| Repo | Profile | Start risk | Outcome |
|---|---|---|---|
| **cobenian-accounts** | app | 🟢 none | Greenfield — born compliant; reference implementation. ✅ |
| **cobenian-core-accounts** | library | 🟢 none | Library profile adopted at scaffold (`profile: library`; no PG/sobelow/migrations/deploy). ✅ |
| **cobenian-cadence** | app | 🟢 none | App profile adopted at scaffold; `workflow_run` deploy + full gate from day one. ✅ |
| **cobenian_companion_umbrella** (Companion) | app (umbrella) | 🟡 moderate | `sobelow` + `mix_audit` + `hex.audit` + gitleaks added; Postgres 17; umbrella-aware sobelow/dialyzer (§3.3); `docker` in Dependabot; linear history on. All gates blocking (`dialyzer_blocking: true`). ✅ |
| **cobenian-agents** (Oversight) | app | 🔴 high | Migrated off the `precommit` CI alias and the in-workflow deploy → reusable `@v1` + `workflow_run`; `credo` + `dialyxir` added and ratcheted to blocking; sobelow findings skipped inline; cowlib CVE bumped; checkout `v7`; `docker` in Dependabot; linear history on. Ratchet **complete** (`nonblocking: ""`, `dialyzer_blocking: true`). ✅ |

---

## 11. Adoption checklist (per repo)

- [ ] Profile chosen (app / library) — §1
- [ ] `ci.yml` with the standard pins and gate order — §3
- [ ] Duplicate-migration check (apps with migrations) — §3.1
- [ ] Umbrella-aware sobelow/dialyzer/test wiring (umbrellas) — §3.3
- [ ] `fly-deploy.yml` via `workflow_run` (apps) — §4
- [ ] `/health` endpoint (apps) — §4
- [ ] gitleaks job (CLI binary) — §5
- [ ] `dependabot.yml` with the repo's ecosystems — §5
- [ ] `FLY_API_TOKEN` secret + first manual `fly launch`/deploy (apps) — §6
- [ ] Branch protection + squash-only + auto-delete + Dependabot updates — §7
- [ ] Governance files (`CLAUDE.md`, `ARCHITECTURE.md`, CODEOWNERS, templates) — §8

### Current rollout status (2026-06-22)

All repos are on the reusable workflow (`@v1`) with the standard branch protection
(PR-required + 0 reviews + linear history + strict `Build and test`), Dependabot, and
the full CI security layer. Adoption is complete.

| Repo | Profile | ci.yml | fly-deploy | branch prot (this std) | dependabot | security layer (gitleaks/sobelow/audits) | risk |
|---|---|---|---|---|---|---|---|
| cobenian-accounts | app | ✅ | ✅ | ✅ | ✅ | ✅ | 🟢 |
| cobenian-core-accounts | library | ✅ | n/a | ✅ | ✅ | ✅ | 🟢 |
| cobenian-cadence | app | ✅ | ✅ | ✅ | ✅ | ✅ | 🟢 |
| cobenian-agents | app | ✅ | ✅ | ✅ | ✅ | ✅ | 🟢 |
| cobenian_companion_umbrella | app | ✅ | ✅ | ✅ | ✅ | ✅ | 🟢 |

Legend: ✅ done · ⚠️ partial/drift · ☐ not started · n/a not applicable.

---

## Changelog

- **1.6 (2026-06-22)** — **Adoption complete.** Refreshed the §10/§11 status tables
  to reflect reality: all five repos are on the reusable `@v1` workflow, every ratchet
  is promoted to blocking, and Oversight has migrated off both its `precommit` CI alias
  and its in-workflow deploy. Recorded the org-wide consistency sweep that closed the
  remaining drift: **`required_pull_request_reviews: { count: 0 }` added to
  core-accounts, cadence, agents, and companion** (they were missing the "require a PR
  before merging" rule — only accounts had the v1.4 fix), the v1.5 bare-`pull_request:`
  trigger propagated to the repos still filtering on `main`, `postgres 17.4` added to
  `.tool-versions` where absent, and the per-repo governance files (`CONTRIBUTING.md`,
  root `ARCHITECTURE.md`) filled in. Softened the now-historical §3 `precommit`-hole and
  §4 in-workflow-deploy notes.
- **1.5 (2026-06-22)** — Caller CI trigger drops the `pull_request: branches:
  [main]` filter (now runs on PRs to any base) so **stacked PRs are CI-verified**.
  `push` still deploys only from `main`. Updated `templates/ci.yml` and the §9
  caller snippet.
- **1.4 (2026-06-22)** — Fix §7: `required_pull_request_reviews` must be
  `{ required_approving_review_count: 0 }`, not `null`. `null` disables the
  "require a pull request before merging" rule (leaving direct pushes to `main`
  open); the 0-count object keeps PRs required with zero approvals (solo self-merge).
  Verified against the live `cobenian-accounts` branch protection.
- **1.3 (2026-06-22)** — Merged the reusable CI workflow with the cobenian-accounts
  session's version into one canonical `Cobenian/.github` set (in
  `org-github-repo/`). Adopted from Accounts: **`dialyzer_blocking`** input (Dialyzer
  **report-only by default**, fixing the v1.2 reusable-workflow inconsistency where
  it defaulted to blocking), **ratchetable `hex_audit`/`deps_audit`** via
  `nonblocking`, and **`profile` required**. Kept from Cadence: the full
  community-health + Dependabot + CODEOWNERS templates and the real
  `.github/workflows/` staging layout. Added `permissions: contents: read` to the
  deploy template. Updated §9 caller snippet and §10 ratchet guidance accordingly.
- **1.2 (2026-06-22)** — Verified v1.1's audit against the live repos (agents =
  Oversight via `oversight` test DB; **318** migrations; `mix precommit` CI alias;
  sobelow+mix_audit present, credo/dialyxir absent; checkout v6 — all confirmed).
  Corrections: (a) use the **gitleaks CLI binary**, not `gitleaks-action@v2`, which
  requires a paid license for org accounts (affected §3 workflow, §5, checklists);
  (b) Oversight **already deploys** via an in-workflow `needs: test` job — recorded
  as drift-to-migrate, not absent (§4, §10, rollout table); (c) added the
  reusable-workflow required-check-naming caveat (§9); (d) `.gitignore` should
  include `erl_crash.dump`/`priv/plts` (§8).
- **1.1 (2026-06-22)** — Consolidated the `cobenian-accounts` `ci-standard.md` into
  the adopted v1.0: added the per-repo breakage audit + the `nonblocking` ratchet for
  safe live-app rollout (§10), umbrella specifics (§3.3), the CI format-hole note and
  fix, `excellent_migrations` as an optional enhancement, and a risk column in the
  rollout table. Superseded the separate `ci-standard.md`.
- **1.0 (2026-06-22)** — Initial standard. Codifies the companion/agents CI base,
  adopts companion's `workflow_run` deploy pattern, adds the CI security layer
  (Sobelow, mix_audit, hex.audit, gitleaks, `deps.unlock --check-unused`),
  standardizes branch protection (linear history, 0 reviews, self-merge), and
  records the Team-plan/no-GHAS constraint.
