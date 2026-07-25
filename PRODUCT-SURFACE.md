# Cobenian Product Surface Standard — REST, MCP & OAuth2 Exposure

**Status:** Draft · **Version:** 0.2 · **Last updated:** 2026-07-25

How a Cobenian product — every Phoenix app **and** every Panel instrument —
**exposes its own programmatic surface** to callers: other Cobenian products,
third-party integrators, LLMs (via MCP), unattended services, and on-behalf-of-a-user
clients. The goal is the same as the other platform standards: **consistency by
default.** Every product's *outbound* surface should look and behave the same, so
integrating with any Cobenian product — by REST, by MCP, or by OAuth2 — is
predictable, testable, and cheap to extend.

> **Canonical home.** This file lives in **`Cobenian/.github`** alongside
> [`STANDARDS.md`](./STANDARDS.md) and [`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md).
> STANDARDS governs how repos are built and shipped; PLATFORM-ADOPTION governs how a
> product **consumes** the platform (inbound: product → Accounts/Foundry/Data); **this
> governs how a product exposes itself** (outbound: caller → product). Normative
> keywords (**MUST**, **MUST NOT**, **SHOULD**, **MAY**) follow RFC 2119.

> **Scope.** Applies to every product that exposes a machine-callable surface —
> Cadence, Orbit, Glean, Foresight, Steward, Companion, the Data APIs, Foundry, and
> **each Panel instrument** — which is its own product hosted by Panel, not an exception
> (§3). A product with no external surface today still
> adopts §1–§6 the moment it grows one. The **in-app admin** surface that governs a
> product from a browser is a separate concern, specified in
> [`IN-APP-ADMIN.md`](./IN-APP-ADMIN.md).

> **Relationship to Accounts.** This standard builds on the Accounts control-plane
> contract and does not restate it. The token shapes, `resolve_token/2 → %Principal{}`,
> capability scopes, principal types, act-class scopes, and the workspace-grant model
> are defined in `cobenian-accounts` `specs/features/product-api/product-facing-api.md`
> (§5, §6), `specs/features/accounts/end-user-grant.md`, and `specs/general/{authentication,authorization,app-integration}.md`.
> This document is authoritative only on **what a product does with them at its own
> edge.**

---

## 0. Why this exists

Cadence shipped the first external API (`specs/features/api/rest-api.md`, ADR-018) and
proved the shape: one `/api/v1`, every caller authenticated by an Accounts-issued JWT,
per-endpoint capability scopes, path-bound workspace scoping, the `act` human
checkpoint, signed outbound webhooks. But that spec is Cadence-specific and explicitly
**defers MCP**. If every product re-derives this — its own scope naming, its own error
envelope, its own webhook signing, its own MCP↔REST split — the surfaces drift exactly
as the platform *facades* drifted before PLATFORM-ADOPTION.

This standard fixes that once. It generalizes the Cadence REST pattern, adds the **MCP
transport** over the same core, states the **OAuth2 resource-server / consent** duties a
product owes, and pins the cross-cutting surface conventions (webhooks, API keys, rate
limiting, metering, audit). The unifying idea is one sentence:

> **A product has one authorization core and many transports. REST and MCP are thin
> adapters over it; the core — not the transport — decides who may do what, in which
> workspace.**

---

## 1. The surface conventions

### S1 — One authorization core, many transports

A product's authorization decisions — scope check, tenant scope, entitlement gate, the
`act` checkpoint — **MUST** live in the domain/context layer, not in a controller or an
MCP tool handler. REST controllers and MCP tools **MUST** be thin adapters that (a)
resolve the caller to a `%Principal{}` (S2), (b) translate the request into a core call,
and (c) render the result. A transport **MUST NOT** carry an authorization path the
other transports lack: any capability reachable by MCP **MUST** be reachable, and gated
identically, by REST, and vice-versa. There **MUST** be no transport-only route that
satisfies a check the core would deny (the generalization of Cadence rest-api §8.4 —
"the API introduces no new autonomy path").

*Rationale: MCP is new and LLM-driven; the safety of the product cannot depend on the
transport a caller happens to use.*

### S2 — Every caller is an Accounts Principal

Every request on every transport **MUST** present an Accounts-issued JWT as a bearer
token and **MUST** be resolved through the Accounts boundary
(`Cobenian.CoreAccounts.resolve_token/2 → %Principal{}`, product-facing-api §5.11) —
**never** by parsing JWT claims in a controller or tool handler. Resolution is offline
on the hot path (JWKS signature + claims, product-facing-api §4.3, §5.11.2). A request
without a valid token **MUST** be rejected `401 unauthenticated`.

The **only** caller distinction a product makes is the `%Principal{}.type` — `:user` (a
human, via an on-behalf-of token) vs `:service` (a product acting as itself). First-party
vs third-party **MUST NOT** be a distinction the product enforces in code; any
difference (allowed scopes, workspaces, rate tier, entitlement) is expressed by **what
Accounts granted the credential**, evaluated through the scopes, entitlements, and
tenant model below (product-facing-api §5.10.4).

### S3 — The product owns its capability-scope vocabulary; Accounts carries it

A product's surface **MUST** be gated by **capability scopes** it defines, named
`"<product>:<resource>:<verb>"`, lowercase and stable (e.g. `cadence:decisions:read`,
`glean:documents:write`). The product **MUST** register its scopes in the Accounts
**product-scope registry** (product-facing-api §5.9.2, via the Platform Admin console);
Accounts carries and grants them but does not interpret them.

Each REST endpoint and each MCP tool **MUST** declare the single capability scope it
requires. A request whose Principal lacks that scope **MUST** be rejected `403
scope_denied`. The check **MUST** be enforced in the core (S1), server-side,
deny-by-default — never only in a controller, a tool description, or the UI.

### S4 — `act`-class scopes are user-only, enforced twice

A capability that performs an **irreversible or externally-visible action** — the human
checkpoint — **MUST** be registered as an `act`-class scope
(`allowed_principal_types = {user}`, product-facing-api §5.9.3) and **MUST** be enforced
in **two** places, belt-and-suspenders (Cadence rest-api §5.4):

1. Accounts refuses to grant/mint it to a `:service` credential (upstream); and
2. the product **MUST** additionally reject a non-`:user` principal at the endpoint/tool
   at request time, **regardless of token claims**.

This invariant — *only a `:user` principal may exercise an `act`-class capability* —
**MUST** hold identically on REST and MCP. An MCP "tool" that acts is therefore usable
only by a client that authenticated a human (S8); an unattended `:service` MCP client
sees read/propose tools only.

### S5 — Tenant scope comes from the token and fails closed

Every workspace-scoped operation **MUST** identify a `workspace_id`, and the product
**MUST** authorize it against the Principal — never trust a client-supplied value as
authoritative:

- REST: the id **MUST** be a path segment, `/api/v1/workspaces/:workspace_id/…`.
- MCP: the id is a **required tool argument**, treated with the same suspicion as a path
  segment.

Authorization follows the Principal's grant mode (product-facing-api §5.10.5): a `:user`
or `explicit` `:service` principal — the `workspace_id` **MUST** be within
`Principal.workspace_ids`; an `all_entitled` `:service` principal — the `workspace_id`
**MUST** be **live-entitled** to the product (§S6). A `workspace_id` outside the grant
**MUST** be rejected `404` (hide-existence, no enumeration). Every query and mutation
**MUST** be scoped by the resolved `workspace_id`; the surface **MUST NOT** be able to
read or write across workspaces. Workspace ids **MUST** be UUIDs.

### S6 — Entitlement is gated at the consumer, on every workspace-scoped request

A validly-signed token with a correct audience is **necessary but not sufficient**
(product-facing-api §5.1.1, token-issuance §8.1). Before serving a workspace-scoped
request the product **MUST** confirm its own product slug is entitled for that
workspace: the coarse `entitlements` claim on the fast path, escalating to the **live
check** (`check_entitlement`, product-facing-api §6.2) before any privileged or
irreversible action. A non-entitled workspace **MUST** be rejected `403`/`404` even
though the token verifies. The fail posture (closed vs open in the pre-launch window)
**MUST** be explicit in the product's config (app-integration §8.2).

### S7 — REST conventions are fixed

A product's REST surface **MUST** follow these, so every Cobenian REST API is
byte-shaped alike (generalizing Cadence rest-api §3, §11–§14):

- **Versioned JSON.** Served under `/api/v1`; breaking changes introduce `/api/v2`;
  additive changes (new fields/endpoints/optional params) **MUST NOT** bump the version.
  Bodies are JSON with `snake_case` fields matching the domain (no rename layer).
- **No browser coupling.** The API **MUST NOT** depend on a cookie, session, or CSRF
  token; every request is authenticated solely by its bearer token.
- **Stable error envelope.** `{ "error": { "code", "message", "details" } }` with a
  stable machine `code`. Status mapping: `401 unauthenticated`, `403 scope_denied` /
  `workspace_forbidden`, `404 not_found` (also cross-workspace, hide-existence), `422
  validation_failed` with field-level `details`, `429 rate_limited`, `409 conflict`.
- **Idempotency.** Non-idempotent writes **MUST** honor an `Idempotency-Key` header
  (replay within a retention window returns the original result); where the domain
  already de-duplicates, the API **MUST** surface the existing resource, not a duplicate.
- **Pagination.** List endpoints **MUST** be cursor-paginated (`limit` + `cursor` →
  `{ data, next_cursor }`, `next_cursor` null at end), **SHOULD** accept an
  `updated_since` delta filter, and **MUST** clamp `limit` to a server max rather than
  reject.
- **Correlation & attribution.** Responses **SHOULD** carry `X-Request-Id`. When a call
  is driven by an end-user, the caller **SHOULD** forward `Cobenian-Client-IP` /
  `Cobenian-Client-User-Agent` for the audit trail (product-facing-api §3.8).
- **Async.** Work that is not synchronously complete **MUST** return `202 Accepted` with
  a resource carrying at least an id and a `status`, pollable by `GET`; the API **MUST
  NOT** block on human-paced work.

### S8 — MCP is an adapter over the same core, authenticated by Accounts

A product that exposes an MCP surface **MUST** do so as a thin adapter over the same
authorization core (S1), not as a parallel implementation:

- **One tool per capability.** Each MCP tool **MUST** map to a product operation gated by
  exactly one capability scope (S3), and **MUST** call the same core function the
  equivalent REST endpoint calls. A tool **MUST NOT** expose a capability the REST
  surface does not, and `act`-class tools obey S4 (usable only by a `:user` principal).
- **Scope-filtered tool listing.** `tools/list` **MUST** return only the tools whose
  required scope the resolved Principal holds; a caller **MUST NOT** discover tools it
  could not invoke.
- **OAuth2 authorization.** The MCP endpoint **MUST** be an OAuth2 **protected
  resource**: it **MUST** publish protected-resource metadata (RFC 9728) that names
  **Accounts** (`https://accounts.cobenian.com`) as its authorization server, so an MCP
  client discovers Accounts and runs the standard authorization-code + PKCE grant
  (end-user-grant.md) — or client-credentials for an unattended `:service` client —
  against Accounts, never against the product. The product **MUST NOT** issue, store, or
  validate any credential of its own; it validates the resulting Accounts JWT on the
  S2 path. An unauthenticated MCP request **MUST** return the `401` +
  `WWW-Authenticate` challenge pointing at the resource metadata.
- **Honest tool semantics.** Tool descriptions and results **MUST** reflect real,
  observable behavior (no fabricated value/ROI, §S12); a read tool **MUST NOT** mutate,
  and an act tool **MUST** state that it acts.

### S9 — Outbound webhooks: one signed, verified, SSRF-guarded model

A product that emits state-change events **MUST** follow one webhook model
(generalizing Cadence rest-api §10), gated by a `<product>:webhooks:manage` scope:

- **Per-workspace registration** under the API
  (`/api/v1/workspaces/:w/webhook_endpoints`, create/list/delete).
- **Stable signed envelope** `{ id, type, workspace_id, occurred_at, data }`, signed
  with a per-endpoint HMAC secret shown **once** at registration (e.g.
  `X-Cobenian-Signature: t=<ts>,v1=<hmac-sha256>`), timestamp included for replay
  rejection.
- **At-least-once, idempotent, bounded.** Delivery is at-least-once with exponential
  backoff and bounded retries; consumers key on event `id`. An endpoint failing
  persistently **MUST** be auto-disabled and its owner able to see it.
- **Ownership verification before delivery.** A newly registered endpoint **MUST** be
  inactive until the registrant proves control of the URL (challenge echo / signed
  verification ping) — never deliver a workspace's data to an unverified URL.
- **SSRF guard.** The server **MUST** require HTTPS and refuse to register or deliver to
  non-public targets (loopback, link-local, private, internal); redirects to such
  targets **MUST NOT** be followed.
- **Polling parity.** Every event type **MUST** have a pull equivalent (§S7 list/read),
  so a consumer without an endpoint gets the same information.
- **Channel separation.** Webhooks are the **machine** channel; they **MUST NOT**
  replace **Accounts notify** (the human channel) or **Foundry Comms** (sending as a
  workspace's connected account). The three are independent (PLATFORM-ADOPTION §2).

### S10 — API keys are a skin over Accounts credentials, never a new auth path

A product **MUST NOT** mint, store, or validate its own long-lived API credentials. If a
product offers a "developer API key" experience, the key **MUST** be an Accounts
**service credential** (client-credentials, product-facing-api §5.3) or OAuth client,
issued/rotated/revoked through Accounts (Platform Admin console §4.2–4.3), and validated
on the same `resolve_token` path (S2). The rationale is product-facing-api §5.3's: the
long-lived secret never rides on API calls, revocation/rotation are real, and
verification reuses the JWKS path. A static, app-local API key as the **only** mechanism
is **non-conforming**. A product's own admin surface (IN-APP-ADMIN) therefore *links to*
Accounts for credential lifecycle; it does not reimplement it.

### S11 — Rate limiting & quotas are per-principal, tiered by entitlement

Every surface (REST and MCP) **MUST** be rate-limited per Principal (per-IP as a
backstop), returning `429 rate_limited` with `Retry-After`. The **tier MUST derive from
the token's entitlements** so first- vs third-party throttles are an Accounts setting,
not product code (Cadence rest-api §14). Usage-based quotas **MUST** be enforced against
Accounts usage/entitlement, not a product-local counter of record.

### S12 — Metering, audit & honesty

Work performed via any surface **MUST** be metered through **Accounts usage ingest**
with `source` attributing the calling principal and, for `:user` principals, `subject`
attributing the person (Cadence rest-api §15). Every state-mutating call **MUST** be
auditable and attributable to the human behind it via the forwarded context (S7,
product-facing-api §3.8.4). Surfaces **MUST** return only honest, observable quantities;
they **MUST NOT** fabricate value, cost, or results on failure (PLATFORM-ADOPTION C4).

---

## 2. First-party, third-party, and the consent gap

2.1. A first-party product-to-product call and a third-party integrator call are the
**same object** to a consuming product: an Accounts JWT resolved to a `%Principal{}`
whose scopes and workspaces are whatever Accounts granted the credential
(product-facing-api §5.10.4). A product **MUST NOT** branch on caller origin.

2.2. **Enabling third-party access today** is an operator action: a Cobenian operator
registers the third party's OAuth client and/or service credential in the Platform Admin
console, choosing its capability-scope allow-list, workspaces (or `all_entitled`), and
audiences. There is no self-serve third-party registration yet.

2.3. **Consent** — a workspace owner approving a third-party client's request to act on
their users' behalf with named scopes — is **deferred in Accounts**
(end-user-grant.md §4.5: first-party clients are auto-approved; a third-party consent
screen is a future addition). This standard records the product's **obligation into
that future flow**: because scope *meaning* lives in the product (S3), each product
**MUST** supply a **human-readable label and description for every capability scope it
registers**, suitable for rendering on a consent screen. A scope registered without a
consent-facing description is **non-conforming** once third-party consent ships.

2.4. **Dependencies on Accounts** (tracked, not owned here): third-party self-serve
client registration, the consent screen, and optional dynamic client registration (RFC
7591) for MCP/LLM clients. Until they exist, third-party and LLM access is
operator-provisioned per 2.2.

---

## 3. Panel instruments are products; Panel is their host

3.1. **Each Panel instrument is a product** under this standard — it has its own Accounts
product slug, its own capability-scope namespace (`<instrument>:<resource>:<verb>`, S3),
its own entitlement, its own OAuth-client / service-credential eligibility, and its own
REST base path and MCP server identity, and it authorizes every caller itself (S1–S6)
exactly as a standalone app does. There is **no** Panel-level surface exception: an
instrument's surface conforms to S1–S12 on its own account.

3.2. **Identity is separate from deployment.** Panel is the shared **host and shell** —
the runtime that mounts instruments and the browser chrome (nav, session, launcher,
shared components) they render within — **not** a shared resource server that terminates
auth on an instrument's behalf. An instrument's product identity (slug, scopes,
entitlement, audience, surface) is its own, independent of the fact that Panel currently
hosts it in a shared runtime. Because identity was never Panel's, an instrument **MAY**
later be extracted to its own deployment with **no** change to its contract, callers, or
registration.

3.3. **Panel-hosted ≠ Panel-authorized.** Hosting many instrument-products in one runtime
is a deployment convenience; it **MUST NOT** collapse their authorization. Each
instrument resolves its own Principal (S2) and runs its own scope, tenant, entitlement,
and `act` checks (S3–S6) for the operation invoked. A shared plug/kit **MAY** perform the
mechanical resolution, but the product slug an instrument checks entitlement against, and
the scope namespace it enforces, are the **instrument's** — never a blanket "Panel"
grant. `tools/list` (S8) for an instrument returns only that instrument's tools the
Principal is scoped for.

3.4. **Substrate is shared; products are distinct.** An instrument remains a composition
over the shared piece vocabulary (`piece × lens × preset × capabilities`, SPEC-PANEL-SUB-001)
and owns no authoritative business/PII data — its rows live in a Data API read through
product-owned facades. That shared substrate is *code reuse*, orthogonal to product
identity: instruments share the substrate and the runtime while remaining independently
registered, entitled, and surfaced products. This is the class the platform tiers call
**services** (narrow, Data-API-backed, Panel-hosted products), as distinct from **apps**
(own data plane and own deployment, e.g. Steward, Companion, Cadence).

---

## 4. Relationship to the other standards

- [`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md) — the **inbound** mirror: how this
  product *consumes* Accounts/Foundry/Data. A product typically does both; the two seams
  are independent (app-integration §10.2).
- [`STANDARDS.md`](./STANDARDS.md) — repo/CI/CD; structured logging (C7) enriches this
  surface's request logs.
- [`IN-APP-ADMIN.md`](./IN-APP-ADMIN.md) — the browser admin that manages this surface
  (webhook endpoints, product policy, audit view, kill-switch).
- **Shared kit.** The mechanical parts of this standard — the `resolve_token` plug, the
  scope-enforcement guard, the error envelope, cursor pagination, the webhook
  registrar/signer/SSRF-guard, the MCP protected-resource metadata + tool dispatcher —
  **SHOULD** ship as an **outbound-surface extension** to `cobenian_core_platform`, which
  today owns the *inbound* consumption kit (`Ref`/`Normalize`/`Errors`/`Tier`/`Port`/
  `Logging`, PLATFORM-ADOPTION §7). Building it out means products write policy, not
  plumbing. Until it ships, products follow this prose and the Cadence reference
  implementation.

---

## 5. Conformance checklist (per product / per instrument)

A product's outbound surface is conforming when:

- [ ] Scope, tenant, entitlement, and `act` checks live in the core; REST and MCP are
      thin adapters with no transport-only authorization path (S1).
- [ ] Every request resolves to a `%Principal{}` via the Accounts boundary; `:user`
      vs `:service` is the only caller branch; no first/third-party branch (S2).
- [ ] Capability scopes are `<product>:<resource>:<verb>`, registered in Accounts, and
      each endpoint/tool declares and enforces exactly one (S3).
- [ ] `act`-class scopes are user-only and rejected for `:service` at request time on
      both transports (S4).
- [ ] `workspace_id` comes from the path/tool-arg, is authorized against the Principal's
      grant/entitlement, fails closed with hide-existence `404`, and no query crosses
      workspaces (S5).
- [ ] Product entitlement is confirmed on every workspace-scoped request — coarse fast,
      live before privileged action (S6).
- [ ] REST is `/api/v1` JSON with the stable error envelope, idempotency keys, cursor
      pagination, correlation id, and `202`+resource for async (S7).
- [ ] MCP tools map 1:1 to scoped operations over the same core, are scope-filtered in
      `tools/list`, and the endpoint is an OAuth2 protected resource pointing at Accounts
      (S8).
- [ ] Outbound webhooks use the signed envelope, ownership verification, SSRF guard,
      auto-disable, and polling parity; distinct from notify/Comms (S9).
- [ ] No product-local long-lived API credential; developer keys are Accounts service
      credentials (S10).
- [ ] Rate limiting per principal, tier from entitlement, `429`+`Retry-After` (S11).
- [ ] Usage metered via Accounts; state-mutations audited & human-attributable; honest
      metrics only (S12).
- [ ] Every registered scope has a consent-facing label/description (§2.3).
- [ ] Each Panel instrument is its own product (slug, scope namespace, entitlement, REST
      base + MCP identity) authorizing its own callers; Panel hosts, it does not
      authorize; identity is separate from deployment (§3).

---

## 6. Out of scope (v1)

Explicitly deferred; **MUST NOT** be assumed by v1 conformance:

- **GraphQL / bulk-export transports** — possible later transports over the same core.
- **Config-as-code plane** — authoring product configuration via API (Cadence rest-api
  §17); the only v1 config surface is webhook endpoints (S9) and what IN-APP-ADMIN
  covers from a browser.
- **Accounts-side third-party self-serve registration, the consent screen, and dynamic
  client registration** — dependencies tracked in §2.4, owned by Accounts.
- **A product `:service` satisfying an `act` checkpoint** — permanently out of scope by
  S4; unattended action arises only from a product's own human-configured autonomy
  policy (e.g. Cadence), never from a scope or principal attribute.

---

## Changelog

- **0.2 (2026-07-25)** — §3 reframed: **each Panel instrument is its own product**
  (own slug, scope namespace, entitlement, REST base + MCP identity) that authorizes its
  own callers, with Panel as the shared host/shell — **identity separate from
  deployment**. Replaces the earlier "Panel is one resource server hosting scope-gated
  surfaces" model. Names the **services vs apps** product classes.
- **0.1 (2026-07-25)** — Initial draft. Twelve surface conventions (S1–S12), the
  first/third-party + consent-gap section, Panel-instrument conformance, relationship to
  the other standards, conformance checklist, and v1 out-of-scope. Generalizes the
  Cadence REST reference (ADR-018) and adds the MCP transport and OAuth2 resource-server
  duties over the Accounts token model.
