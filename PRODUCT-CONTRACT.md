# Cobenian Product Contract Standard — one declaration, every surface

**Status:** DRAFT — for review · **Version:** 0.1 · **Last updated:** 2026-08-06

How a Cobenian product **declares** its programmatic surface once, as machine-readable
data, and how every artifact that surface needs — routes, OpenAPI, MCP tools, webhook
catalog, the Accounts scope manifest, facade clients, and the conformance suite — is
**derived** from that one declaration rather than hand-written alongside it.

> **Canonical home.** This file lives in **`Cobenian/.github`** alongside
> [`STANDARDS.md`](./STANDARDS.md), [`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md),
> [`PRODUCT-SURFACE.md`](./PRODUCT-SURFACE.md), [`IN-APP-ADMIN.md`](./IN-APP-ADMIN.md),
> and [`EVENTS-CATALOG.md`](./EVENTS-CATALOG.md). Normative keywords (**MUST**,
> **MUST NOT**, **SHOULD**, **MAY**) follow RFC 2119.

> **Relationship to PRODUCT-SURFACE.** PRODUCT-SURFACE (S1–S12) is authoritative on
> **what a surface must be** — one authorization core, Accounts principals, capability
> scopes, fixed REST conventions, MCP as an adapter, signed webhooks. This standard does
> not restate or relax any of it. It is authoritative only on **the form the declaration
> takes and what is generated from it**. Where the two could be read to conflict,
> PRODUCT-SURFACE wins on semantics; this document wins on artifact provenance.

> **Scope.** Every product that exposes a machine-callable surface: Accounts, Foundry,
> Steward, Logs, the Data APIs, and **each Panel instrument** (which is its own product,
> PRODUCT-SURFACE §3). A product with no machine surface today adopts this the moment it
> grows one.

---

## 0. Why this exists

PRODUCT-SURFACE fixed the *shape* of a surface. `SPEC-PANEL-SURFACE-001` then fixed how
Panel **mounts** a declared surface: an instrument declares `scopes/0`,
`rest_resources/0`, `mcp_tools/0`, `webhooks/0` as pure data, and a shared host turns
that data into mounted transports (PANEL-SURF-005, -011). That model is correct and this
standard adopts it wholesale.

What neither document says is that the declaration is a **source artifact you generate
from**. Today, per capability, a product hand-writes:

1. the REST controller and its param handling,
2. the MCP tool definition and its JSON Schema,
3. the webhook event shape,
4. the scope string — *again*, retyped into the Accounts product-scope registry through
   the Platform Admin console (S3),
5. the consumer's `RemoteClient` **and** a `StubClient` that must independently enforce
   the same contract (PLATFORM-ADOPTION; PANEL-SURF-015),
6. the tests that check all of the above conform to S1–S12.

Six hand-maintained expressions of one fact. The costs are already visible:

- **No product in the fleet publishes an API document.** `open_api_spex` appears in zero
  `mix.exs`. Integrators read source.
- **S3.1 exists because of hand-copying.** Four paragraphs on the `-` vs `_` near-miss
  hazard, ending in *"Declaration and registration MUST be copied from a single source
  … never retyped."* That requirement has no mechanism behind it.
- **Surfaces don't get built.** Ten of Panel's fifteen instruments have no machine
  surface. The per-capability cost is the reason.
- **Stub/Remote parity is asserted, not guaranteed.** A StubClient drifts silently until
  a contract test catches it, if one was written.

The rule this standard adds is one sentence:

> **A capability is declared once. Every transport, document, client, scope registration,
> and conformance check for it is generated from that declaration and committed as a
> build output — never authored a second time.**

---

## 1. The contract is one artifact

- **C1 — One contract module per product.** A product exposing a machine surface **MUST**
  declare it in a single module implementing the `Cobenian.CorePlatform.Contract`
  behaviour (§4). For a Panel-hosted instrument, this is the instrument's `surface` module
  (PANEL-SURF-002); the two are the same thing under different names, and the Panel
  behaviour **MUST** be defined in terms of this one rather than in parallel to it.

- **C2 — The contract is data, not code paths.** Every callback **MUST** return compiled,
  side-effect-free data (lists of structs), so the contract can be read at build time
  without starting the application, opening a connection, or invoking the product. It is
  the same discipline PANEL-SURF-005 already requires, extended to every product.

- **C3 — The declaration points at the core, never at a transport.** Every operation's
  `mfa` **MUST** name a function in the product's authorization core — the same function
  the browser surface calls for that capability. A contract **MUST NOT** name a handler
  living in a controller, an MCP tool module, a channel, or the host
  (PRODUCT-SURFACE S1, PANEL-SURF-006). The contract is a pointer to the core, not a
  place to put logic.

- **C4 — Derived artifacts are build outputs.** Every artifact in §3 **MUST** be produced
  by a generator reading the contract, **MUST** be committed to the repo, and **MUST NOT**
  be edited by hand. A hand-edit is a build failure, not a style problem (§5).

---

## 2. What the declaration contains

The struct fields are normative; their module homes are a build detail. Where a struct
already exists in `SPEC-PANEL-SURFACE-001` §3.4, this standard **hoists** it unchanged
unless noted.

- **C5 — `%Scope{}`** — as PANEL-SURF-007: `name` (`"<namespace>:<resource>:<verb>"`,
  S3.1), `class` (`:read | :write | :act`), `label`, `description`. `label` and
  `description` are **REQUIRED** — they are the consent-screen text (PRODUCT-SURFACE
  §2.3), and a scope without them is non-conforming.

- **C6 — `%Operation{}`** — the unit this standard adds. One capability, projected onto
  zero or more transports:

  | Field | Meaning |
  |---|---|
  | `id` | stable, unique within the product; the OpenAPI `operationId` and the MCP tool name derive from it |
  | `scope` | exactly one declared `%Scope{}` name (S3) |
  | `mfa` | the core function (C3) |
  | `input` / `output` | schemas (C8) |
  | `summary` / `description` | honest, observable behavior only (S12) |
  | `act?` | **MUST** agree with `scope.class == :act`; drives the user-only double enforcement (S4, PANEL-SURF-018) |
  | `rest` | `%RestProjection{path, verb, idempotent?}` or `nil` |
  | `mcp` | `%McpProjection{name, annotations}` or `nil` |

  An operation with both projections is served on both transports **through the same
  `mfa`**. An operation with one projection is reachable only there — permitted, and
  governed by §6.

- **C7 — `%WebhookEvent{}`** — as PANEL-SURF-009a: `type`
  (`"<namespace>.<resource>.<event>"`), `scope`, `schema`. Declaring the event type is
  what makes it registrable, pollable, and catalogued (C12).

- **C8 — One schema language, because OpenAPI 3.1 *is* JSON Schema.** `input`, `output`,
  and `%WebhookEvent{}.schema` **MUST** be expressed in a single schema term that renders
  losslessly to **JSON Schema 2020-12**. OpenAPI 3.1 adopted JSON Schema 2020-12 outright,
  and MCP requires JSON Schema for `inputSchema` — so the *same value* satisfies the MCP
  tool definition, the OpenAPI request/response body, and runtime request validation.
  A product **MUST NOT** maintain a second schema for a second transport.

---

## 3. What is generated

For a contract `C`, the generator **MUST** produce all of the following, and a product
**MUST NOT** hand-maintain any of them:

- **C9 — Routes and request validation.** REST routes for every operation with a `rest`
  projection, mounted under the product's base (S7; `/api/v1/instruments/<slug>` for a
  Panel instrument, PANEL-SURF-021), with the fixed error envelope, status mapping,
  `Idempotency-Key`, cursor pagination, and `X-Request-Id` correlation supplied by the
  host (PANEL-SURF-022). Requests are validated against `input` before the `mfa` is
  entered. Authorization remains in the core (C3, S1) — generation supplies plumbing, it
  **MUST NOT** become an authorization path.

- **C10 — An OpenAPI 3.1 document.** Served at the product's base + `/openapi.json` and
  committed to the repo. It **MUST** list, per operation, the required capability scope
  and whether it is `act`-class, so an integrator can see what a token needs before
  requesting one. This is the fleet's first API document; there is no exemption for
  "internal" products.

- **C11 — MCP tool definitions.** `tools/list` for the product's own MCP server identity
  (S8, PANEL-SURF-024), built from the `mcp` projections, scope-filtered per principal,
  with `act`-class tools absent for a `:service` principal and rejected at call time
  regardless (S4, PANEL-SURF-025). `annotations.readOnlyHint` / `destructiveHint`
  **MUST** be derived from `scope.class`, not declared independently — an honest hint is
  a computed fact, not an author's claim.

- **C12 — A webhook catalog.** The product's declared event types, their subscriber
  scope, and their `data` schemas, emitted in the form `EVENTS-CATALOG.md` consumes, so
  the fleet event catalog stops being hand-maintained.

- **C13 — The Accounts scope manifest.** A machine-readable manifest of every declared
  scope with its class, label, and description, for registration in the Accounts
  product-scope registry. This **satisfies S3.1's single-source requirement by
  construction**: the contract module is the one source, and registration consumes the
  manifest rather than a human retyping the string. The `-`/`_` near-miss hazard S3.1
  documents cannot arise from a generated manifest.

- **C14 — The facade client pair.** For each consuming product, a `RemoteClient` and a
  `StubClient` generated together from the same contract, behind the product-owned facade
  behaviour PLATFORM-ADOPTION requires. Generating both from one source is what makes
  PANEL-SURF-015's demanded stub/remote *parity* a property of the build instead of a
  test someone remembered to write. A hand-written `StubClient` for a contracted surface
  is non-conforming.

- **C15 — The conformance suite.** The mechanically checkable subset of PRODUCT-SURFACE
  §5 and PANEL-SURF §12, generated per product: scope naming and description presence,
  `act?`/`class` agreement, `mfa` arity and export, REST↔MCP scope-vocabulary
  consistency (§6), error-envelope and pagination shape, `tools/list` scope filtering,
  `act`-tool user-only rejection, webhook envelope and SSRF guard. `test/support/instrument_conformance.ex`
  in `cobenian-panel` is the seed and **SHOULD** be refactored into the generated suite
  rather than duplicated. Checks requiring product judgment (is a description *honest*?)
  stay human and stay in the checklist.

---

## 4. Where the kit lives

- **C16 — The kit is `Cobenian.CorePlatform.Contract`, in `cobenian-core-platform`.**
  That library is the only one strictly below every surface-bearing application —
  `cobenian-accounts` itself depends on it — so a kit there can be adopted by Accounts,
  Panel, Steward, Logs, Foundry, and the Data APIs without a dependency inversion.

- **C17 — The kit MUST NOT depend on `cobenian-core-accounts`.** Principal resolution and
  entitlement are reached through **the product's own facade**, passed to the kit as
  configuration (PLATFORM-ADOPTION; PANEL-SURF-014, -015). The kit knows the *shape* of a
  principal, never the Accounts SDK. This keeps the contract kit usable by Accounts
  itself, and keeps the platform boundary intact.

- **C18 — The kit is plumbing, and says so.** It generates and mounts. It **MUST NOT**
  make an authorization decision, hold product state, or become a base module a product
  inherits behavior from. A product **MUST** remain able to hand-write any single
  transport for an operation and drop that projection from its contract — the escape
  hatch is part of the design, not a failure of it.

---

## 5. Drift is a build failure

- **C19 — Regeneration must be a no-op.** CI **MUST** run the generator and fail if the
  working tree changes. This is the mechanism behind C4; without it, "generated" decays
  into "generated once, then edited."

- **C20 — Declared scopes must match registered scopes.** CI (or a scheduled fleet job)
  **MUST** compare each product's generated scope manifest (C13) against what Accounts
  actually has registered for that product, and fail on divergence in either direction —
  a declared-but-unregistered scope fails closed at request time with a `403`, and a
  registered-but-undeclared scope is a grant nobody enforces. Both are silent today.

---

## 6. Scope-parity (resolved)

PRODUCT-SURFACE **S8** originally required *endpoint*-parity: *"One tool per capability …
MUST call the same core function the equivalent REST endpoint calls. A tool MUST NOT
expose a capability the REST surface does not."* `SPEC-PANEL-SURFACE-001` PANEL-SURF-024
departed from it and flagged the departure as *"a Panel interpretation to reconcile
upstream."*

**Resolved 2026-08-06: S8 is amended to scope-parity** (PRODUCT-SURFACE v0.4). The Panel
interpretation is now the fleet rule, and this standard gives it structure.

- **C21 — One vocabulary, independent projections.** The shared spine between transports
  is the product's **single declared scope vocabulary** (C5). An `%Operation{}`'s `rest`
  and `mcp` projections (C6) are declared **independently**: an MCP tool **MAY** compose
  several core functions and have no REST twin, and a REST resource **MAY** have no tool.
  A projection **MUST NOT** introduce a capability class the vocabulary does not already
  express, **MUST** be gated by exactly one scope from it, and **MUST** be checked by the
  same core (C3). `act`-class stays user-only on both transports (S4).

The invariant that survives the amendment is the one that mattered: **MCP adds a
transport, never a new authorization or autonomy path.** What it gives up is the claim
that an LLM-facing surface must be shaped like a CRUD surface, which was never true and
was suppressing tool design.

---

## 7. Adoption sequence

Smallest blast radius first; each step independently shippable.

1. **Hoist the structs.** `%Scope{}`, `%Operation{}`, `%WebhookEvent{}` and the
   `Contract` behaviour into `cobenian-core-platform`. No generation yet.
   **This MUST land before `SPEC-PANEL-SURFACE-001` §10 step 1**, which would otherwise
   define the same structs Panel-locally and require a migration across every instrument
   to undo.
2. **Generate the cheap artifacts.** OpenAPI (C10) + the scope manifest (C13) from
   contracts that already exist as data. No runtime change, immediate value: the fleet's
   first API document and the end of retyped scopes.
3. **Pilot on Cases.** Cases is the reference instrument with every dimension green.
   Re-express its hand-built surface as a contract and confirm the generated REST + MCP
   is behaviourally identical. If it is not, the model is wrong — find out here.
4. **Generate routes and MCP** (C9, C11) for new surfaces. Groundskeeper and Reeve are
   the Tier-2 instruments owed a surface; they should be the first *built* this way.
5. **Facade clients and the conformance suite** (C14, C15).
6. **Drift checks** (C19, C20) in CI.
7. **Migrate Time & Billing** (PANEL-SURF-031…034) last — it is the hardest case, and
   worth attempting only once the generator is proven on greenfield.

---

## 8. Out of scope (v0.1)

- GraphQL, gRPC, and bulk-export transports.
- Generating anything from the contract other than surface artifacts — no schema
  migrations, no LiveView, no infrastructure-as-code, no scaffolding of an application.
- Non-Elixir client SDKs. C14 covers the Elixir facade pair only; a TypeScript client
  from the OpenAPI document (C10) is downstream and needs no new declaration.
- Dynamic registration of scopes at runtime. C13 produces a manifest; how Accounts
  ingests it (console import vs. an idempotent registration endpoint) is an Accounts
  decision, owed its own ADR.
- The in-app admin surface (IN-APP-ADMIN A1–A6). `%AdminSection{}` stays in the Panel
  declaration; it is browser-surface, not machine-surface, and generalizing it fleet-wide
  is separate work.

---

## 9. Conformance checklist (per product)

- [ ] Exactly one contract module implementing `Cobenian.CorePlatform.Contract` (C1),
      returning compiled data only (C2).
- [ ] Every `mfa` names a core function the browser surface also calls; no transport-only
      handler (C3).
- [ ] Every scope carries a consent `label` and `description` (C5).
- [ ] `act?` agrees with `scope.class` on every operation; MCP annotations derived, not
      declared (C6, C11).
- [ ] One schema per operation, JSON Schema 2020-12, serving MCP, OpenAPI, and runtime
      validation alike (C8).
- [ ] REST and MCP projections declared independently, both gated by scopes from the one
      vocabulary, neither introducing a capability class it does not express (C21, S8).
- [ ] OpenAPI 3.1 document generated, committed, and served; scope and `act`-class listed
      per operation (C10).
- [ ] Webhook events feed the fleet catalog (C12); scope manifest generated (C13).
- [ ] `RemoteClient` and `StubClient` generated as a pair; no hand-written stub for a
      contracted surface (C14).
- [ ] Conformance suite generated and green (C15).
- [ ] Kit consumed from `core-platform`, with the Accounts facade injected — no
      `core-accounts` dependency in the surface path (C16, C17).
- [ ] CI fails on regeneration diff (C19) and on declared-vs-registered scope divergence
      (C20).

---

## 10. References

- [`PRODUCT-SURFACE.md`](./PRODUCT-SURFACE.md) v0.3 — S1–S12, §3 (Panel instruments are
  products), S3.1 (scope naming). Authoritative on semantics.
- [`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md) — facade conventions (behaviour +
  RemoteClient + StubClient), the platform boundary C17 preserves.
- [`IN-APP-ADMIN.md`](./IN-APP-ADMIN.md) — A1–A6; out of scope here (§8).
- [`EVENTS-CATALOG.md`](./EVENTS-CATALOG.md) — the catalog C12 feeds.
- `cobenian-panel` `specs/features/panel/panel-surface.md` (SPEC-PANEL-SURFACE-001) §3,
  §10 — the declaration model this hoists, and the build sequence §7 step 1 must precede.
- `cobenian-panel` `test/support/instrument_conformance.ex` — the C15 seed.
- `cobenian-panel` `lib/cobenian_panel/mcp/{server,tools}.ex` — the hand-written MCP this
  replaces (PANEL-SURF-031…034).
- `cobenian-accounts` `specs/features/product-api/product-facing-api.md` §5.9.2 — the
  product-scope registry C13 targets.

---

## Changelog

- **0.1 (2026-08-06)** — Initial draft. Twenty-one conventions (C1–C21): the contract
  module, `%Operation{}` with independent REST/MCP projections over one scope vocabulary,
  a single JSON Schema 2020-12 term across transports, seven generated artifacts, the
  `core-platform` home with no `core-accounts` dependency, and drift-as-build-failure.
  Hoists the `SPEC-PANEL-SURFACE-001` §3.4 declaration structs fleet-wide. §6 adopts
  **scope-parity** and lands the matching **S8 amendment** in PRODUCT-SURFACE v0.4,
  closing the reconciliation PANEL-SURF-024 raised for upstream. Prompted by an
  evaluation of ForkLaunch's manifest-driven generation model (fleet evaluation note,
  2026-08-06, held outside this repo).
