# Cobenian Engineering Standards — GitHub, CI & CD

**Status:** Adopted · **Version:** 1.7 · **Last updated:** 2026-08-23

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

> **Companion standard.** This file governs how repos are *built and shipped*.
> How product code *talks to the platform* (Accounts, Foundry, Data APIs) lives in
> [`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md) — the six client-adoption
> conventions every consuming product follows.

---

## 1. Repository profiles

Every repo is one of three profiles. The profile decides which parts of this
standard apply. (An **umbrella** is still the *application* profile, with the
invocation tweaks noted in §3.3.)

**Application** and **Library** are Elixir. **Client** is not — see §1.1.

| | **Application** | **Library** | **Client** |
|---|---|---|---|
| Examples | cobenian-accounts, cobenian-cadence, cobenian_companion_umbrella (umbrella) | cobenian-core-accounts | cobenian-mobile |
| Language / toolchain | Elixir | Elixir | TypeScript, React Native + Expo |
| CI (format/compile/credo/test/dialyzer) | ✅ | ✅ | ❌ — equivalents in §1.1 |
| Postgres in CI | ✅ (if it has a Repo) | only if it has DB-backed tests | ❌ |
| Sobelow (Phoenix SAST) | ✅ | ❌ (no web surface) | ❌ |
| Migration checks | ✅ (if it has migrations) | ❌ | ❌ |
| `/health` endpoint | ✅ | ❌ | ❌ (not a service) |
| CD to Fly | ✅ | ❌ | ❌ — **store submission, §1.1** |
| Hex publish workflow | ❌ | optional (on tags) | ❌ |
| Dependabot | ✅ mix | ✅ mix | ✅ **npm** |
| gitleaks | ✅ | ✅ | ✅ |
| mix_audit / hex.audit | ✅ | ✅ | ❌ — `npm audit` instead |
| Branch protection + governance files | ✅ | ✅ | ✅ |
| Reusable Elixir CI workflow (§9) | ✅ | ✅ | ❌ — cannot call it |

---

### 1.1 The Client profile

A **client** is a repo that produces an artifact installed on someone else's
device — today, `cobenian-mobile`. It is in this standard because governance,
branching, and secret-scanning must not vary by language. Everything else does.

**What carries over unchanged.** Squash-only merges · linear history ·
auto-delete head branches · 0 required approving reviews · `main` always
releasable · branch protection (§7) · gitleaks (§5) · Dependabot ·
`CODEOWNERS` · PR and issue templates · Conventional Commits (§2).

**What replaces the Elixir gate.** A client's `ci.yml` is its own — it does
**not** call the reusable Elixir workflow (§9), which has no meaning here. The
required status check is still named **`Build and test`** so §7's branch
protection applies verbatim:

| Elixir gate | Client equivalent |
|---|---|
| `mix format --check-formatted` | Prettier `--check` |
| `mix compile --warnings-as-errors` | `tsc --noEmit` |
| `mix credo --strict` | ESLint, no warnings |
| `mix test` | the project's test runner |
| `mix dialyzer` | — (TypeScript covers it) |
| `mix deps.audit` / `hex.audit` | `npm audit --audit-level=high` |
| `mix sobelow` | — (no web surface) |

**What has no Elixir analogue — and matters most.** A client is the only profile
where **merging to `main` does not ship anything**, and the only one that cannot
be rolled back.

1. **Releases are reviewed artifacts, not merges.** A build is submitted to a
   store and approved by a third party — hours to days. Plan for it; do not
   promise a same-day fix.
2. **There is no hotfix path.** A bad build stays in users' hands until the next
   one is approved. This is the single largest operational difference from every
   other repo in the org, where merge-to-`main` auto-deploys and the remedy for a
   bad deploy is another deploy.
3. **Old versions persist for months.** Users do not upgrade on your schedule.
   **Every server surface a client consumes is therefore a public API: additive
   changes only.** Never remove a field, never re-type one, never tighten a
   validation an old build would now fail. This constraint lands on the *server*
   repos, not this one — a breaking change in Panel or Accounts breaks phones
   that cannot be patched.
4. **Ship a minimum-supported-version check in the first release.** The client
   asks a server on launch whether it is too old and, if so, blocks with an
   upgrade prompt. It is the only emergency brake a client has, and it **cannot
   be retrofitted** — the builds that would need it are already in the field.
5. **Store credentials are release infrastructure.** Signing keys, API keys, and
   the review demo account are covered by §6 like any other secret. A demo
   account that rots blocks every future release, so it is maintained, not
   assumed.

**Adoption.** A client repo satisfies §11's checklist with the §1.1 substitutions
above. `profile:` in the §9 caller does not apply, because there is no caller.

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
| Elixir | `1.20.3` |
| OTP | `29.0.5` |
| Postgres service | `postgres:17` |
| `actions/checkout` | `v7` |
| `actions/cache` | `v5` |
| `actions/upload-artifact` | `v4` |
| `erlef/setup-beam` | `v1` |
| `superfly/flyctl-actions/setup-flyctl` | SHA-pinned (`ed8efb3`, = `v1.6`) |

`.tool-versions` is the single source of truth for the language pins (`erlang
29.0.5`, `elixir 1.20.3`, `postgres 17.4`); CI mirrors it. Let Dependabot keep the
action versions current.

`setup-flyctl` is pinned to a **commit SHA**, not a tag, because that step
installs the binary that then runs with `FLY_API_TOKEN` against production. It
was previously on `@master` — a floating branch ref, so any push to a
third-party repo would have landed in every fleet deploy unreviewed.

Dependabot now watches THIS repo (`.github/dependabot.yml`). It has to: consumer
repos deliberately ignore `Cobenian/.github/*` in their own configs, since the
`@v1` float is how shared hardening reaches them without a per-repo edit. That
makes this file the only place the third-party actions above can be kept current
— and with no updater here they drifted (`actions/cache` v5 while v6 shipped,
`actions/upload-artifact` v4 while v7 shipped). Those bumps are majors and are
deliberately left for Dependabot to raise as individually reviewable PRs.

**Moving the `v1` tag:** the fleet consumes `@v1`, so merging to `main` here
changes nothing on its own — `v1` must be retargeted at the new commit for the
12 caller repos to pick it up. That retarget takes effect on every repo's next
CI or deploy run at once, so treat it as a fleet-wide change, not a docs merge.

`_build` is cached on `mix.lock`, which means it crosses commits that change source
without changing the lock. Compiling incrementally on top of those artifacts makes
`--warnings-as-errors` non-deterministic, so `elixir-ci.yml` runs **`mix clean`
immediately before the compile gate**. That drops only first-party artifacts and keeps
compiled dependencies, so the type check is honest and still cheap (8s on foundry, the
fleet's largest umbrella). Do not "optimise" that step away — it has caught a false red
(foundry 3f3bce1, 2026-08-21) and it is the only thing preventing the silent false-green
case, where a stale caller is never re-checked and a real warning is never emitted.

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
          elixir-version: "1.20.3"
          otp-version: "29.0.5"

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
        # Report-only repos map dialyxir's exit 2 to a ::warning:: rather than using
        # continue-on-error (which still stamps a red ##[error] on a green run).
        # Exit 1/3 (tool could not run) always fails. See the reusable workflow.
        run: mix dialyzer --format github

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

### 3.4 Log-attribution guard (spawned processes)
A spawned `Task`/process does **not** inherit the caller's per-process `Logger`
metadata, so one that logs inside an attributed request or job emits lines with no
`user_id`/`workspace_id`/`actor`. Every app that depends on `cobenian_core_platform`
**must** enable the `UnattributedSpawn` credo check, which flags such spawns so they
get wrapped in `Cobenian.CorePlatform.Logging.with_context/1` (or re-apply metadata
inline). Start from [`templates/credo.exs`](templates/credo.exs); CI asserts both that
the check is enabled **and** that it's loaded via `requires:` — the check ships behind
`if Code.ensure_loaded?(Credo.Check)` and credo isn't on the dep's compile path, so
without the `requires:` entry credo silently ignores it and the guard is inert.

---

### 3.5 A rule belongs in the module that can enforce it

**A rule stated in a module that cannot enforce it is a comment, and comments do not get
adopted.** State a rule beside the function that implements it. Where a rule must be
referenced elsewhere, the other place carries a pointer, not a second copy of the
statement.

This is not a style preference. It is the mechanism behind a real fleet-wide defect, and
the shape is worth recognising because it looks like good documentation right up until it
fails:

`Cobenian.CorePlatform.Readiness` — the shared readiness kit — correctly stated that a
liveness probe must never depend on another service, because a probe a platform *acts* on
must only report faults that remediation can fix. The module then shipped `self_checks`,
`dependencies`, `render/2` and `report/1`: all readiness, no liveness. The rule was
correct, written down, in a shared library, and in the one module structurally incapable of
satisfying it.

Six products adopted that module. The rule reached none of them. Four went on to answer
`503` from `/health` on any database error, so a single Postgres incident would have failed
every machine's health check at once, removed them all from rotation, and taken `/version`
down with them — the endpoint every deploy and conformance result is interpreted through. A
fifth satisfied the rule only by checking nothing at all.

Not five independent mistakes. One missing abstraction, beside a correct rule nobody could
follow.

The test to apply: **if a reader adopts this module, can they act on this sentence?** If
not, the sentence is in the wrong file — and the usual fix is that the module should have
grown a function rather than a paragraph.

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
| `version_path` | `""` | optional path returning the running commit SHA (e.g. `/version`); when set, the deploy asserts the live app reports `head_sha` |

Secrets `FLY_API_TOKEN` (required) and `HEX_ORG_KEY` (optional) flow through
`secrets: inherit`. Like the reusable CI, the deploy workflow is pinned by tag
(`@v1`); bump deliberately.

### 4.2 A deploy may be superseded — and a green deploy is not proof

Two properties of this design bite together. Both are handled in the reusable workflow,
so no app needs a change.

**Deploys can run backwards.** CI takes minutes, and the deploy fires on CI
*completion*. When two merges land close together, the older commit's CI can finish
**after** the newer merge — firing a deploy that ships the older code over the newer.
Observed 2026-08-02 in `cobenian-panel`: #184 merged at 14:44, #183's CI finished at
14:45:28 and deployed its own older SHA; prod silently served the previous commit for
four minutes, until #184's own CI completed. The reusable workflow now **refuses to
deploy a SHA that is no longer the tip of the default branch**, re-checked *after* the
`deploy-group` concurrency slot is acquired (a deploy can go stale while queued behind
another). Skipping is always safe — whatever is now the tip deploys from its own CI run.

**Neither the run status nor the image label proves what shipped.** In that incident the
deploy went green, and `gh run list` reported the run's `headSha` as the *newer* commit
(it reports the branch head at trigger time, not the payload's `head_sha`). The Fly image
label agreed with it, because the label comes from the workflow input while the build
comes from the checkout. The only honest signals were the `commit` field in the app's
logs and the running code itself.

So when diagnosing, read the deploy run's own log —
`gh run view <id> --log | grep "head_sha:"` — for the SHA the reusable workflow actually
received. And prefer `version_path`, which makes CI assert that the running release
reports the SHA it claims; adding such an endpoint is the cheapest way to turn "did it
ship?" into a single `curl`.

#### And once it *has* shipped: read the code from that SHA, not from your checkout

`/version` answers *"did it ship?"*. The next question is almost always *"what does the
running code do?"* — and that one is usually answered by reading a file in a local
directory, which is a different question wearing the same clothes.

**Any claim of the form "production does X because the code says so" reads the file at the
SHA `/version` reports:**

```
git show '<served-sha>:path/to/file.ex'
```

A repo directory is just whatever branch it happens to be sitting on. `grep -rn` over a tree
containing worktrees is worse: it spans branches nobody asked about and returns them with
equal authority, ordered by directory name, with nothing in the output distinguishing `main`
from someone's half-finished feature.

**Four instances in one night, 2026-08-21/22, in two families.** The first two are *a fact
true somewhere, cited as true in production*; the second two are ancestry run against the
wrong operands:

| | what went wrong |
|---|---|
| a line number cited for `connectors/sync/harvest.ex` | read `:160` from an **unmerged feature branch**; on the served `e55f9d7` the same entry is `:231` |
| the same file read to settle what production emits | read from a local checkout at `0c53176` / `claude/decision-100`, **divergent** from `e55f9d7` — not merely behind it |
| a deploy "confirmed" by `git merge-base --is-ancestor <served> <served>` | tautological — **passes for any input** |
| a live change reported as unshipped | `--is-ancestor <branch-head> <served>` answers NO after a squash, because the branch head is never an ancestor of `main` |

The third is the dangerous member of the family: it produces false *confidence* rather than
false doubt, and it looks exactly like a real check. The fourth is its mirror, and cost a
session an hour reporting a deployed fix as missing.

Both are fixed by choosing the right subject: compare the **PR's merge commit** against the
served SHA — `gh pr view N --json mergeCommit -q .mergeCommit.oid` — never a SHA against
itself, never a branch head. Ancestry is a good tool; it is the operands that were wrong.

#### A static read proves **today's** behaviour, and cannot settle a question about data that already exists

This one survives any amount of care about SHAs. **You can read exactly the right SHA and
still be answering the wrong question.**

Events already emitted and rows already written were produced by an *older* build. So when
the data predates the code you are reading, the source argument is **corroboration**, and
something measured over the actual data has to carry the claim.

**The test is how many assumptions each rests on.** On 2026-08-22 the question was whether a
connector emitted a field as an explicit `null` or omitted the key:

- *"the connector writes the key unconditionally"* — read from the source. Needs one
  assumption: that emission has not changed since those events were written.
- *"`key ABSENT: 0`"* — counted over the payloads a drain actually folded. Needs none.

Fewer assumptions wins, so the measurement carries it and the source read explains *why* it
came out that way. Both were true; only one was evidence. **Say which is which** — a document
that presents corroboration as proof is harder to correct later than one that was simply
wrong, because everything in it is accurate.

### 4.1 Clustering (required for every app running DNSCluster)

Every deployable Phoenix app **must** ship `rel/env.sh.eex` (copy
[`templates/rel-env.sh.eex`](templates/rel-env.sh.eex) verbatim — it is app-agnostic).
Fly provides the private 6PN network and `<app>.internal` DNS, but Erlang clustering is
**not** automatic: the node must be named by a **stable basename over IPv6** so it matches
what DNSCluster dials.

- Name the node `<%= @release.name %>@$FLY_PRIVATE_IP` (release name is stable and
  identical on every machine). **Never** key the basename on `$FLY_IMAGE_REF` — it changes
  per deploy, so the machines never match and `Node.list()` stays empty.
- Set `RELEASE_DISTRIBUTION=name`, `ERL_AFLAGS="-proto_dist inet6_tcp"`,
  `DNS_CLUSTER_QUERY=$FLY_APP_NAME.internal`.

Why it matters: without correct clustering, a LiveView app **reconnect-loops** (blue
progress bar every few seconds, full page reload) the moment a second machine autostarts —
a long-poll/reconnect landing on the other, un-clustered node can't find its process. It is
**silent until you scale**, so the reusable CI (§3) fails any app that runs DNSCluster
without a valid `rel/env.sh.eex`. Verify after deploy with two started machines:
`fly ssh console -a <app> -C "/app/bin/<rel> rpc 'IO.inspect(Node.list())'"` — expect a peer.

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

   **Report-only does not mean invisible, and it does not mean a red X.** A
   report-only Dialyzer run surfaces each finding as a `::warning::` annotation and
   the step ends with one summary `::warning::` — never the runner's
   `##[error]Process completed with exit code N`. That error annotation is what
   `continue-on-error` produces, and it makes an advisory report look exactly like a
   real gate failure in the run summary; a green run wearing a red X teaches everyone
   to stop reading the annotations panel. (Panel CI #1647, 2026-08-27: green,
   red X, 237 findings nobody had read.)

   The one thing report-only still **fails** on is Dialyzer not completing — a PLT
   build failure, a crash, or a stale `.dialyzer_ignore.exs` entry that no longer
   matches (`list_unused_filters`). "The tool did not run" must never be allowed to
   read as "the tool found nothing".

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

- **1.7 (2026-08-23)** — **Added the `Client` repo profile (§1, §1.1)** for repos
  producing an artifact installed on someone else's device — first instance
  `cobenian-mobile` (React Native + Expo). The standard previously assumed every
  repo was Elixir, so a non-Elixir repo had no governed shape at all. Governance,
  branching, branch protection and gitleaks carry over **unchanged**; the Elixir
  gate is replaced by a per-language equivalent that keeps the required check
  named `Build and test` so §7 applies verbatim. Records the three things no
  Elixir profile has to reason about: **merge to `main` ships nothing**, **there
  is no hotfix**, and **old versions persist for months — so every server surface
  a client consumes is a public API, additive changes only.** That last one binds
  the *server* repos, not the client. Also mandates a minimum-supported-version
  check in a client's first release, because it cannot be retrofitted.
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
