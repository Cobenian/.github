# Cobenian Cross-Product Events Catalog

**Status:** Draft · **Version:** 0.1 · **Last updated:** 2026-07-04

The contract for how Cobenian products **react to each other** — the Wave C of
[`PLATFORM-ADOPTION.md`](./PLATFORM-ADOPTION.md). Products emit domain events onto
the **Foundry Events** spine; other products subscribe. No product calls another
product directly, and no product re-implements another's domain to know what
happened — it listens.

> **Canonical home.** `Cobenian/.github`, alongside `PLATFORM-ADOPTION.md`. This
> catalog is the source of truth for event **names** and **payloads**; a producer
> or consumer that disagrees with it is the bug.

---

## 1. Rules

- **Transport is Foundry Events.** Producers call `Cobenian.CoreFoundry.Events.emit/3`;
  consumers subscribe with a Foundry **trigger** (webhook to the product's
  `/api/v1/foundry/events` endpoint, HMAC-verified per `FND-SIGN-001`) or pull via
  `stream/1`. Workspace scoping rides the token claim — never in the payload.
- **Emit is best-effort and off the hot path.** A failed emit **MUST NOT** fail the
  user action that triggered it. Emit after the local write commits (outbox or
  post-commit), map failures through `Cobenian.CorePlatform.Errors`, and move on.
- **Delivery is at-least-once.** Consumers **MUST** be idempotent, keyed on the
  event's `id`. A duplicate delivery is a no-op.
- **Reference, don't copy.** Payloads carry a `subject` as a
  `Cobenian.CorePlatform.Ref` (or a product-scoped id) plus the minimum `data` a
  consumer needs to decide whether to act. Consumers read canonical records
  (Directory, Finance, the producer's API) rather than trusting fat payloads.
- **No secrets or PII in payloads.** Emails, phone numbers, channel addresses stay
  in the owning system; events carry references, not contents.
- **Names are `<product>.<entity>.<action>`,** action in the past tense. Names are
  stable; a breaking payload change is a new event (`…​.v2`), not a mutation.

## 2. Envelope

Every event's payload follows one shape:

```elixir
Cobenian.CoreFoundry.Events.emit(
  "glean.questionnaire.completed",
  %{
    subject: Cobenian.CorePlatform.Ref.to_map(subject_ref), # what it's about
    data: %{...},                                            # minimal decision inputs
    occurred_at: iso8601,
    idempotency_key: stable_key                              # producer-stable, for dedupe
  },
  token: workspace_service_token                             # aud: cobenian-foundry
)
```

## 3. Catalog

| Event | Producer | `subject` | `data` (minimal) | Consumers |
|-------|----------|-----------|------------------|-----------|
| `glean.response.captured` | Glean | `Ref(glean, response, id)` | `questionnaire_id`, `contact_ref?` | Orbit |
| `glean.questionnaire.completed` | Glean | `Ref(glean, questionnaire, id)` | `response_count`, `subject_ref?` | Orbit, Cadence |
| `orbit.relationship.changed` | Orbit | `Ref(directory, contact, id)` | `from_temp`, `to_temp`, `reason` | Cadence |
| `orbit.campaign.sent` | Orbit | `Ref(marketing, campaign, id)` | `recipient_count` | Cadence, Foresight |
| `cadence.decision.needs_you` | Cadence | `Ref(cadence, decision, id)` | `playbook`, `urgency` | (Accounts notify — existing) |
| `cadence.playbook.completed` | Cadence | `Ref(cadence, run, id)` | `playbook`, `outcome` | Orbit |
| `foresight.alert.raised` | Foresight | `Ref(foresight, entity, id)` | `severity`, `signal` | Cadence |

Rows are additive: a producer may emit an event with **no** consumer yet (the
half of a future choreography), and a consumer subscribes when it has a reason to
act. An unconsumed event is not dead code — it's the seam.

## 4. Reference choreography (Wave C proof)

The first end-to-end chain, each hop over Foundry Events:

1. A respondent finishes a questionnaire → **Glean** emits
   `glean.questionnaire.completed`.
2. **Orbit** consumes it, updates the contact's relationship temperature, and emits
   `orbit.relationship.changed`.
3. **Cadence** consumes that and, if a playbook watches the signal, opens a decision
   (`cadence.decision.needs_you`) for a human.

No product imported another. Each reacted to a named fact on the spine.

## 5. Adding to the catalog

1. Add the row here first (name + producer + subject + data + consumers).
2. Producer emits per §2, best-effort, after commit.
3. Consumer registers a Foundry trigger to its events endpoint and handles the
   event idempotently.
4. If the payload must change incompatibly, mint `…​.v2` and migrate consumers
   before retiring the old name.

## Changelog

- **0.1 (2026-07-04)** — Initial catalog: Glean/Orbit/Cadence/Foresight domain
  events + the Glean→Orbit→Cadence reference choreography.
