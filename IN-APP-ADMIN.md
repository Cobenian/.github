# Cobenian In-App Admin Standard

**Status:** Draft · **Version:** 0.1 · **Last updated:** 2026-07-25

How a Cobenian product — every Phoenix app and every Panel instrument — exposes an
**in-app admin surface**: the browser screens a workspace's own owners/admins use to
govern **that product, for their workspace**. It is the third and last tier of Cobenian
administration, and the only one a *product* owns; the other two belong to Accounts.
The goal, as everywhere, is **consistency by default**: product admin should look and
behave the same across the suite, and never quietly re-implement a control-plane
concern.

> **Canonical home.** Lives in **`Cobenian/.github`** alongside
> [`STANDARDS.md`](./STANDARDS.md), [`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md),
> and [`PRODUCT-SURFACE.md`](./PRODUCT-SURFACE.md). Normative keywords follow RFC 2119.

> **Scope.** Applies to every product with per-workspace configuration or product data
> to govern. It builds on the Accounts role model (`cobenian-accounts`
> `specs/general/authorization.md`), the app-integration boundary
> (`specs/general/app-integration.md`), and the Platform Admin console
> (`specs/features/admin/console.md`). It is the browser complement to
> [`PRODUCT-SURFACE.md`](./PRODUCT-SURFACE.md) (the machine surface).

---

## 0. The three tiers of administration

Cobenian has **three** distinct admin surfaces. Confusing them is the most common design
error this standard exists to prevent.

```
  ┌──────────────────────────────────────────────────────────────────────────┐
  │ 1. PLATFORM ADMIN            accounts.cobenian.com/admin                    │
  │    Operator: Cobenian staff  (User.is_system_admin)                         │
  │    Owns: service credentials, OAuth clients, signing keys, product catalog  │
  │          & rate card, cross-workspace support, system audit.                │
  │    → cobenian-accounts specs/features/admin/console.md  (EXISTS)            │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 2. WORKSPACE PORTAL          accounts.cobenian.com                          │
  │    Operator: workspace owner / admin                                        │
  │    Owns: identity, members, roles, seats, billing, entitlements,           │
  │          cross-app user preferences, notification routing.                  │
  │    → cobenian-accounts specs/features/accounts/*  (EXISTS)                  │
  ├──────────────────────────────────────────────────────────────────────────┤
  │ 3. IN-APP ADMIN              <product>/…/admin   (scoped to one workspace)  │
  │    Operator: workspace owner / admin  (+ product seat, §3)                  │
  │    Owns: product settings, product data governance, product-local policy,  │
  │          integrations (webhooks/API visibility), product audit,            │
  │          the product session kill-switch.                                   │
  │    → THIS STANDARD  (NEW)                                                    │
  └──────────────────────────────────────────────────────────────────────────┘
```

The governing rule:

> **Who a user is, and what they may do → Accounts (tiers 1–2). What they did or
> configured *inside this product* → in-app admin (tier 3), for one workspace, keyed on
> the Accounts identity.**

This is the app-integration §3 boundary, applied to administration.

---

## 1. What in-app admin owns

Deny-by-default: if a concern is owned by Accounts (tier 1 or 2), in-app admin **MUST
NOT** reimplement it (§2). In-app admin owns only the following, always scoped to the
**acting workspace**:

**A1 — Product settings.** The workspace-scoped settings of the product. These **MUST**
be stored and read through **Foundry Settings** (`:workspace` scope), **not** the app's
own database (app-integration §4.1). In-app admin is the *presentation* of those
settings; it is not a second store.

**A2 — Product data governance.** Bulk operations, retention configuration, export, and
deletion of the **product data the app owns** (app-integration §3), plus servicing
data-subject requests over it. This is the one area whose *record* lives in the product.

**A3 — Product-local policy.** Policy whose meaning lives in the product and that
Accounts deliberately does not interpret: feature enablement within an entitlement,
approval/autonomy policy (e.g. Cadence's autonomy graduation), which **teams** may use
which feature/instrument (using `/api/v1/me/teams`, the workspace-group primitive), and
per-workspace defaults. Policy **MUST** narrow within what the workspace is entitled to;
it **MUST NOT** widen access beyond entitlement or seats.

**A4 — Integrations & surface management.** Register/manage **outbound webhook
endpoints** (PRODUCT-SURFACE §S9). Show a **read-only** view of which Accounts OAuth
clients / service credentials currently reach this workspace's product data and with
what scopes (sourced from Accounts; the product does not own the registry). Where an
operator needs to *change* that, in-app admin **MUST** link to the Accounts portal /
Platform Admin, not reimplement registration (§S10, §2).

**A5 — Product audit.** A workspace-scoped, read-only view of **product actions** — who
did what in this product — complementary to the Accounts audit (which covers identity,
billing, entitlement, credentials). Entries **MUST** be attributable to the human behind
the action, including actions taken via the API/MCP on-behalf-of a user
(PRODUCT-SURFACE §S12).

**A6 — Product session kill-switch.** An admin action to **bump a user's app-local
`session_version`** (app-integration §6.5), instantly revoking that user's live product
sessions — the app-initiated instant revocation of app-integration §7.3. This is
distinct from Accounts "sign out everywhere" (which the workspace portal owns) and
operates only within this product.

---

## 2. What in-app admin MUST NOT do

2.1. In-app admin **MUST NOT** manage, or keep as its own source of truth, any
Accounts-owned control-plane concern: **identity, membership, roles, seats, billing,
entitlement/subscription, service-credential or OAuth-client registration, signing
keys, or the product catalog.** Where an admin needs one of these, the surface **MUST**
link to the relevant Accounts tier (portal for members/seats/billing; Platform Admin for
credentials), and **MUST NOT** present a shadow editor for it.

2.2. In-app admin **MAY** display a **read-only reference projection** of workspace
members (from the app's projection or `/api/v1/me/*`, app-integration §5) so admins can,
e.g., pick a user for a product-local policy or the kill-switch. It **MUST NOT** create,
remove, or re-role members, and **MUST NOT** treat the projection as authoritative
identity (app-integration §4).

2.3. In-app admin **MUST NOT** grant product access. Opening/using the product is
**seat-gated** by Accounts (authorization §4); an admin adds seats in the workspace
portal, not here.

---

## 3. Access control

3.1. **Role gate.** In-app admin **configuration** actions **MUST** require the acting
user's workspace **role** to be `owner` or `admin` (authorization §3.2). `member` and
`observer` **MUST NOT** reach any admin mutation; `observer` **MUST NOT** mutate
anything anywhere.

3.2. **Seat interaction.** Role and seat are independent axes (authorization §4). An
owner/admin **without** a product seat **MAY** administer the product's configuration
(A1, A3, A4, A6) but **MUST NOT** be able to *open/use* the product itself without a
seat. A product **MAY** additionally require a seat for data-touching admin actions (A2,
A5) where viewing product data is itself product use; that choice **MUST** be explicit
in the product's policy.

3.3. **Server-side, deny-by-default.** Enforcement **MUST** be server-side at
mount/dispatch (a LiveView `on_mount` / plug), never UI-only (authorization §7). Admin
routes for a workspace the user is not an owner/admin of **MUST** fail closed — `404`
hide-existence, consistent with the Platform Admin console §3.1 and workspaces §7.3.

3.4. **Tenant scoping.** Every admin screen and action **MUST** be scoped to a single
`workspace_id` derived from the authenticated session and a verified active membership
(authorization §5), never from a client-supplied identifier alone.

3.5. **Cobenian staff.** A System Administrator (tier 1) **MAY** be granted
cross-workspace support access into a product's admin for support, but every such access
**MUST** be audited (authorization §6). Building that support tooling is **out of scope
for v1** beyond this allowance.

---

## 4. Audit

4.1. Every in-app admin **mutation** **MUST** write a product AuditEvent with the acting
user as actor, the `workspace_id`, and enough detail to reconstruct the change — mirroring
the Platform Admin console's audit discipline (console §5) at the product tier.

4.2. Security-sensitive actions — the kill-switch (A6), webhook endpoint
create/rotate/delete (A4), retention/deletion of product data (A2), and product-local
policy changes that affect access (A3) — **MUST** be audited and **SHOULD** be surfaced
in the product audit view (A5).

---

## 5. Consistency & UX

5.1. **Shared shell (recommended).** The mechanical parts — the `on_mount` role/seat
guard, the workspace-scoped audit view, the kill-switch action, and the webhook-endpoint
management UI — **SHOULD** ship as part of the same outbound-surface extension to
`cobenian_core_platform` proposed in PRODUCT-SURFACE §4, so every product's admin is the
same shell with product-specific sections plugged in. Until it ships, products follow
this prose.

5.2. **Branding & theming.** Admin screens **MUST** follow each product's
`specs/general/ui-and-branding.md` and **MUST** support light/dark theming, per the
Cobenian Elixir/LiveView standards.

5.3. **Link, don't fork.** Wherever an admin need crosses into an Accounts tier (§2),
the surface **MUST** present a clear labeled link to the correct Accounts screen rather
than a partial local reimplementation.

---

## 6. Conformance checklist (per product / per instrument)

- [ ] Admin is clearly tier 3: it governs product settings/data/policy/integrations/
      audit/kill-switch for one workspace, and nothing Accounts owns (§0, §1, §2).
- [ ] Product settings go through Foundry Settings, not the app DB (A1).
- [ ] Product data governance acts only on app-owned data (A2).
- [ ] Product-local policy narrows within entitlement/seats, never widens (A3).
- [ ] Webhook endpoints are managed here; credential/registration changes link out to
      Accounts (A4, §2.1).
- [ ] A workspace-scoped, human-attributable product audit view exists (A5).
- [ ] The app-local `session_version` kill-switch is exposed (A6).
- [ ] Config actions require owner/admin role; use is seat-gated; observer never mutates
      (§3.1–§3.2).
- [ ] Enforcement is server-side at mount/dispatch, deny-by-default, hide-existence
      `404`, tenant-scoped from the session (§3.3–§3.4).
- [ ] Every admin mutation is audited with actor + workspace (§4).
- [ ] Follows product branding + light/dark theming; links out rather than forking (§5).

---

## 7. Out of scope (v1)

- **Cross-workspace product support tooling** for Cobenian staff (§3.5) — the flag and
  its auditing exist; the tooling is deferred.
- **Editing Accounts-owned concerns from within a product** — permanently out of scope
  by §2; always a link-out.
- **A live-editable platform configuration** — as with the Platform Admin console
  (console §4.10), product config that is a deploy/env concern stays that way in v1.

---

## Changelog

- **0.1 (2026-07-25)** — Initial draft. The three-tier admin model, the six things
  in-app admin owns (A1–A6), the boundary of what it MUST NOT do, role/seat access
  control, audit, shared-shell/UX consistency, conformance checklist, and v1
  out-of-scope.
