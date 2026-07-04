# Cobenian Platform Adoption Standard — Foundry & Data APIs

**Status:** Draft · **Version:** 0.2 · **Last updated:** 2026-07-04

How a Cobenian product consumes the platform layers — **Accounts** (identity),
**Foundry** (capabilities), and **Data APIs** (canonical business records). The
goal is the same as the CI/CD standard: **consistency by default**. Every
product's platform seam should look and behave the same, so the boundary is
predictable, testable, and cheap to extend.

> **Canonical home.** This file lives in **`Cobenian/.github`** alongside
> [`STANDARDS.md`](./STANDARDS.md). STANDARDS.md governs how repos are built and
> shipped; this governs how product code talks to the platform. Normative
> keywords (**MUST**, **SHOULD**, **MAY**) follow RFC 2119.

> **Scope.** Applies to every product that consumes Foundry and/or the Data APIs
> (Cadence, Orbit, Glean, Foresight, and future products). Products that reach
> external systems by another route (e.g. Companion via Oversight/Steward partner
> tokens + MCP) are **out of scope by design** and MUST record that as an ADR
> (§8) rather than leaving it implicit.

---

## 0. Why this exists

The shared SDKs — [`cobenian_core_foundry`](https://github.com/Cobenian/cobenian-core-foundry)
and [`cobenian_core_data_apis`](https://github.com/Cobenian/cobenian-core-data-apis)
— already own the hard, uniform parts: HTTP transport, retries, the `{"data": …}`
envelope, a **stable tagged-error vocabulary** (`{:error, %Error{reason: …}}`),
telemetry, and Req-plug test injection. Token *minting* lives in
`cobenian_core_accounts`.

What each product still writes for itself is a **facade** over those SDKs. As of
2026-07-03 four products wrote four different facades — diverging on shape,
normalization, token threading, error mapping, and config keys, with two latent
bugs traced directly to that drift. This standard removes the drift by fixing
**six conventions** and backing the mechanical ones with a shared kit
(`cobenian_core_platform`, §7).

---

## 1. The six conventions

### C1 — One facade shape MUST be used

A product's platform seam **MUST** be a *behaviour + RemoteClient + StubClient*
triple per layer:

- a **behaviour** (`@callback`) that the product's contexts depend on;
- a **RemoteClient** implementing it over the SDK;
- a **StubClient** implementing it for dev/test.

Contexts and LiveViews **MUST NOT** call `Cobenian.CoreFoundry.*` or
`Cobenian.CoreDataApis.*` directly — only through the behaviour, selected by
config (§6). The facade **MAY** curate a subset of surfaces (a product need not
expose every Foundry capability), but every surface it does expose goes through
the triple. Monolithic single-module facades and per-context ad-hoc clients are
**non-conforming**.

*Reference implementation: Cadence (`lib/cobenian_cadence/foundry/`).*

### C2 — Token acquisition MUST be uniform

- The bearer token **MUST** be the **first argument** of every facade function.
- End-user requests **MUST** pass the caller's session access token.
- Background, scheduled, or anonymous work **MUST** mint a **per-workspace**
  service token via `cobenian_core_accounts` (token-exchange / client-credentials)
  — never a static, long-lived token.
- A missing/blank token **MUST** short-circuit to `{:error, :unauthorized}`
  without a network call.
- The service-token **audience MUST be the layer boundary**, not the product:
  - Foundry calls → `aud: "cobenian-foundry"`
  - Data APIs calls → `aud: "cobenian-products"`

  Per-product audiences (e.g. `"cobenian-glean"`) are **non-conforming** and
  will fail authorization at the platform edge.

### C3 — One reference shape and shared normalizers MUST be used

Wire JSON is string-keyed and shape-variant. For the cross-product concepts a
product actually handles (contacts, companies, invoices, …), it **MUST** normalize
at the facade boundary using the shared helpers, and **MUST NOT** hand-roll
per-product or per-context normalizers. A product that owns its own data plane and
doesn't project these shared shapes simply has nothing to normalize here.

- A cross-layer reference is the canonical struct
  `%Cobenian.CorePlatform.Ref{api: ..., type: ..., id: ...}`.
- Shared `normalize_contact/1`, `normalize_company/1`, `normalize_invoice/1`,
  etc. produce atom-keyed maps with agreed key names (`:ref`, `:name`,
  `:company`, `:amount`, …).
- The same concept **MUST** use the same key name across every product. A contact
  ref is `:ref` everywhere; an invoice id is `:id` everywhere.

### C4 — Error mapping MUST be honest and go through the shared mapper

Facade functions **MUST** map SDK errors through `Cobenian.CorePlatform.Errors`
rather than hand-rolling per-seam logic, and **MUST NOT** fabricate a result on
failure (no invented metrics, drafts, or IDs) — an honest error beats a plausible
lie.

- `:budget_exceeded` and `:blocked` **MUST** be surfaced to the caller (they are
  user-actionable).
- By default every other failure collapses to a single `:unavailable`.
- A product that *acts on* a more granular reason — e.g. Cadence resolving a ref
  treats `:not_found` differently from a transport error, or a Comms seam
  distinguishes `:invalid_request` (a suppressed recipient) — **MAY** surface the
  reasons it needs via `Errors.flatten(result, surface: [...])`. The rule is
  *honest, shared mapping*, not mandatory collapse.

### C5 — Inference tiers MUST use the shared vocabulary

For a product that routes LLM calls through **Foundry Inference**:

- The only tier names are `"fast"`, `"balanced"`, `"smart"`.
- Tier **MUST** be chosen by *purpose* through named constants
  (e.g. `@tier_extract Tier.fast()`, `@tier_judge Tier.smart()`), not scattered
  string literals at call sites.

### C6 — Config and test seams MUST be uniform

- Config keys are the same in every product:
  `config :my_app, :foundry_client, ...` and `config :my_app, :data_client, ...`
  (`RemoteClient` in prod, `StubClient` in dev/test).
- Products **MUST** test contexts against the StubClient — never the network.
  The shared kit provides a `use Cobenian.CorePlatform.Port` macro so the
  behaviour/stub wiring is identical everywhere.

---

## 2. Layer boundaries (what goes where)

- **Accounts** — who you are and what you may do. Identity, entitlements, usage
  metering, notifications *to Cobenian users*. Products keep a thin **reference
  projection** of users (id + `session_version` + display cache), never an
  authoritative user table.
- **Foundry** — capabilities: Inference, Comms, Directory, Events, Learning,
  Memory, Prediction, Storage, Vault, Connectors, Orchestration.
- **Data APIs** — canonical business records: Finance, Projects, Marketing,
  Inventory, Signals. A product that *owns* a data plane (e.g. Foresight's
  observation log) **MUST NOT** duplicate it into Data APIs; it references and
  reads canonical records instead.
- **notify vs Comms.** Notifications to Cobenian users go through **Accounts
  notify**. Sending *as a workspace's connected account* to any recipient goes
  through **Foundry Comms**. Products **MUST NOT** blur the two.

---

## 3. Conformance checklist (per product)

A product's platform seam is conforming when all of the following hold:

- [ ] Foundry + Data seams are behaviour + RemoteClient + StubClient triples (C1)
- [ ] Contexts/LiveViews never call an SDK module directly (C1)
- [ ] Token is first arg; background work mints per-workspace tokens (C2)
- [ ] Service-token audiences are `cobenian-foundry` / `cobenian-products` (C2)
- [ ] All normalization uses `cobenian_core_platform` helpers (C3)
- [ ] Errors mapped via the shared mapper; no fabrication on failure (C4)
- [ ] Inference tiers use named constants over the shared vocabulary (C5)
- [ ] Config keys are `:foundry_client` / `:data_client`; tests use stubs (C6)
- [ ] Out-of-scope layers (if any) are recorded as an ADR (§8 of STANDARDS)

---

## 4. Rollout & conformance ratchet

New products adopt the kit from day one. Existing products migrate in three
waves (tracked separately in the rollout plan):

- **Wave A — standardize the seam.** Publish `cobenian_core_platform`; refactor
  each facade to the triple + shared helpers. Behaviour-preserving; this closes
  the known drift bugs as a side effect. A product only takes a Wave-A change
  where the kit applies *without changing behaviour* — a product that deliberately
  surfaces granular reasons (C4) or doesn't yet route through Foundry Inference
  (C5) or Directory/Data (C3) adopts the kit in the wave that introduces that
  surface, not before.
- **Wave B — close wired-but-dormant gaps.** Adopt the surfaces each product has
  scaffolded but not activated (see rollout plan) — which is also where those
  products pick up the kit's tiers and normalizers.
- **Wave C — compose across products via Events.** A shared Events catalog so
  products react to each other instead of re-integrating.

Once a product is conforming, a lightweight test (`assert Facade uses the shared
behaviour`) keeps it from regressing, mirroring the CI ratchet in
[`STANDARDS.md` §10](./STANDARDS.md).

---

## Changelog

- **0.2 (2026-07-04)** — Refined from first implementations (Glean, Orbit). C4 no
  longer mandates collapse-to-`:unavailable`: products that *act on* a granular
  reason (Cadence ref resolution, Comms suppression) surface it via
  `Errors.flatten(surface: …)`. C3/C5 scoped to the concepts/surfaces a product
  actually uses. Rollout notes that granular-reason and not-yet-on-Inference
  products adopt the kit in the wave that introduces the surface.
- **0.1 (2026-07-03)** — Initial draft. Six conventions, layer boundaries,
  conformance checklist, three-wave rollout.
