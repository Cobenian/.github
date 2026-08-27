# Cobenian Delivery Contract

**Status:** Draft · **Version:** 0.2 · **Last updated:** 2026-08-27

The contract for how a Cobenian product **gets a message to somebody**. Two systems
implement it — **Accounts Notify** for people inside the account graph, **Foundry
Comms** for people outside it — and this is the shape they both conform to.

> **Canonical home.** `Cobenian/.github`, alongside [`EVENTS-CATALOG.md`](./EVENTS-CATALOG.md).
> Where an implementation disagrees with this document, one of the two is a bug; say
> which in a PR rather than letting them drift.

They are deliberately **not merged**. Merging would put customer-consent machinery in
the path of "tell an operator the build broke", and colleague-preference machinery in
the path of a client email. What they share is the *shape* below, not an implementation.

---

## 1. The pipeline

Every send, in either system, is these five stages in this order.

```
  intent  →  resolution  →  policy  →  dispatch  →  outcome
```

### 1.1 Intent — the caller's whole vocabulary

A caller says: **reach this audience, from this origin, with this message.**

- **`audience`** — *who or what*. A principal (a user, a group), a place (a feed, a
  channel), or a contact. Never an address.
- **`origin`** — *on whose behalf*. See §2; this is the stage most likely to be
  under-specified in an implementation.
- **`message`** — content, plus a routing key (`event_type` in Notify) that says what
  kind of thing this is.

**A caller MUST NOT name a transport.** Not a channel, not an address, not a
connection. The one permitted exception is a *hint* the system may override
(`Comms` accepts `hints`; forcing a specific connection is `COM-CHAN-005`), and a
hint that cannot be honoured MUST NOT fail the send.

**A caller MUST NOT hold the configuration behind a name it uses.** Both systems
already do this and it is the pattern worth naming: Notify's **feed key** is a stable
name whose destination the workspace owns, and Comms' **mail identity** is a stable
name whose server token and verified `From` the platform owns. In both, the caller
writes a short string — `"ops"`, `"support"` — and learns nothing about where it goes
or what it sends from.

### 1.2 Resolution — the system picks the channel

The system turns the audience into one or more concrete channels. `COM-CHAN-004` states
it for Comms ("the `channel` Comms **resolved** — not one the caller picked"); Notify's
equivalent is that a product "never chooses channels, sees channel addresses, or handles
group membership".

Resolution decides **fan-out**, and fan-out is a property of the audience, not the
message:

| Audience | Copies |
|---|---|
| a user | one |
| a group | one **per member** |
| a `people` feed | one per member of the group it points at |
| a `place` feed | exactly one |
| a contact | one |

The count is the thing implementations MUST make visible before somebody picks the
wrong audience — a group of three is three Slack messages, which is right for "a
decision needs you" and wrong for a digest.

### 1.3 Policy — send, hold, coalesce, or drop

Policy decides **whether** a resolved address is actually used. It is not the same
question in the two systems, and that difference is the reason there are two systems:

- **Inside the account graph**, the governing facts are the person's own
  **preferences** and the workspace's routing. Consent is implicit in membership.
- **Outside it**, the governing facts are **consent and suppression** — a recipient who
  has opted out, bounced, or complained. This is a legal position, not a preference.

Both MUST be able to answer *hold* as well as *send* and *drop*: a message may be
withheld for later coalescing (a digest) or parked for review. A policy decision MUST be
recorded, not silently applied — a suppressed send that leaves no trace is
indistinguishable from a send that never happened.

### 1.4 Dispatch — the channel knows how

Dispatch is per-channel and knows nothing about audience or policy. It receives a
resolved address and content, and returns success or a typed failure.

### 1.5 Outcome — recorded, with enough provenance to answer back

Every send MUST record what happened. Beyond an audit trail, the outcome record MUST
carry enough provenance to **route a reply back to the origin** — see §2.

Delivery is asynchronous and at-least-once. A caller MUST NOT read success at the API
boundary as evidence of delivery: an accepted send that later bounces is normal, and a
`202` means *accepted*, not *delivered*.

---

## 2. Origin, and why it is not just attribution

Origin is where a message came *from*. The reason to record it is not branding — it is
that **a channel a message goes out on is usually a channel somebody can reply on**, and
a reply is only useful if it can be routed back to whatever produced the message.

**Comms conforms today.** `Comms.Message` records the recipient, the resolved channel
and the connection, and says why: *"The resolved channel + connection are provenance: an
inbound reply can come back."* The `+trace` sub-address and per-identity Postmark inbound
streams exist to make that work.

**Notify does not, yet.** A `Notification` records `source_product`, the `workspace`, and
the recipient — but not the acting user, and there is no inbound path at all. That was
sound while Notify only reached colleagues by email and in-app. It stops being sound the
moment a `place` feed points at a Slack channel: **that is a two-way surface being used
one-way**, and somebody will reply in it.

Accordingly:

- A send **SHOULD** record the acting user where one exists, alongside the product and
  workspace it already records. Unattended sends legitimately have no user; that is a
  distinct value, not a missing one.
- A system that delivers to a two-way channel **SHOULD** have a defined answer for an
  inbound reply, even if that answer is "dropped, and logged as dropped". Silence is the
  one unacceptable answer, because it looks identical to working.

---

## 3. The boundary between the two systems

Not "people vs places" — both systems can reach both. Comms routes `slack`, `sms` and
`teams` through `Connectors.Client.send/3`, and a Comms recipient may be *"an email
address, phone number, or channel id"*. A Slack channel is a place, and Comms reaches it.

The boundary is **whose policy applies**:

| | Accounts Notify | Foundry Comms |
|---|---|---|
| Recipient is | inside the account graph | outside it |
| Governed by | the person's preferences | consent + suppression |
| Consent | implicit in membership | explicit, revocable, auditable |
| Replies | no inbound path today (§2) | routed back by design |
| Names a destination by | feed key | contact, or a forced connection |
| Names an origin by | product (+ workspace) | mail identity |

A product choosing between them **MUST** ask who the recipient is, not what the message
is about. An invoice reminder to a customer's client is Comms even though it is about
billing; a billing alert to the workspace owner is Notify even though it is about the
same invoice.

---

## 3.5 When somebody replies

People reply. A `place` feed points at a Slack channel; somebody types an answer under it.
This is not an edge case to be designed away — it is what a two-way surface is for.

### 3.5.1 What happens today

| Channel | What Notify sends as | Where a reply goes |
|---|---|---|
| email | `from: {"Cobenian", "notifications@cobenian.com"}`, **no `Reply-To`** | a Cobenian mailbox, outside every product |
| Slack | `chat.postMessage` with the OAuth token stored on the channel — **Notify's own Slack app**, not Foundry's | nowhere; Notify has no webhook |
| Teams | Graph, token resolved through the install | nowhere |
| SMS | Twilio | nowhere |

Three of the four are silent, and silence is the failure mode that costs most: a person
answers, nothing happens, and there is no signal to anybody that an answer was given. It
looks exactly like a channel nobody is watching.

Comms, by contrast, was built for this: per-identity Postmark servers each with their own
inbound stream, and a `+trace` sub-address on the `Reply-To` derived from the identity's
`From`, so an inbound lands back on the message that produced it.

### 3.5.2 A reply to a *place* is not a reply to a person

A `place` feed delivers one message addressed to nobody in particular. When one member of
that channel answers, that is not the addressee responding — it is one person in the room
speaking about something the room was told. Which of the six people in the channel it was
"for" is not a question with an answer, and an implementation that invents one will be
wrong.

So the correlation a reply supports is **to the message**, not to a recipient:
*this human said this, under that notification*.

### 3.5.3 Receive a reply; do not become a conversation

Foundry **Conversations** already models a two-way place properly — threading, verified
inbound, opaque refs, and `conversations.message.received` carrying `actor` (who spoke),
`in_reply_to` (which of our messages), and `inbound_message_ref` (how to answer them).
Notify **MUST NOT** rebuild that.

Nor may Notify delegate to it: Foundry depends on `cobenian_core_accounts`, and Accounts
depends on no Foundry SDK. Routing Notify's delivery through Conversations would invert
the stack.

What is left is the useful middle, and it is much smaller than either:

> **A delivery system SHOULD be able to report that a human responded, and MUST NOT
> pretend one did not.**

Concretely, a **reply receipt** — not a conversation:

- It carries *what was said*, *who said it*, and *which notification it landed under*.
- It is surfaced to the product as an event. The product decides what a reply means; if it
  wants a real exchange it starts one through Conversations or Comms, which are built for
  that.
- Notify does **not** thread, render cards, accept interactions, or post back. Sending
  stays one-way.

For email this is a `Reply-To` carrying a trace token plus an inbound endpoint — the shape
Comms already proves. For Slack and Teams it is an events subscription on the app Notify
*already owns a token for*, which is a webhook and a signature check, not a chat framework.

### 3.5.4 The minimum, if even that is too much

Where a reply cannot be received, the destination **SHOULD** say so at the point somebody
would reply — a footer, a thread reply from the bot, anything that distinguishes "this
channel does not take answers" from "nobody read yours". An unanswerable channel that
looks answerable is worse than an obviously one-way one.

---

## 4. Conformance

An implementation conforms when:

1. A caller can express intent without naming a transport (§1.1).
2. Resolution is the system's, and fan-out is visible before a send (§1.2).
3. Policy can hold as well as send and drop, and records its decision (§1.3).
4. Outcomes are recorded with provenance sufficient to route a reply (§1.5, §2).
5. A name used by a caller (`feed_key`, `mail_identity`) resolves to configuration the
   caller cannot read (§1.1).

**Known non-conformance**, tracked rather than hidden:

| System | Clause | State |
|---|---|---|
| Accounts Notify | §2 origin / reply path | No acting user recorded; no inbound path on any of its four channels (§3.5.1). |
| Accounts Notify | §3.5.4 visible one-wayness | A Slack `place` feed looks answerable and is not; a reply is silently lost. |
| Accounts Notify | §1.1 name-resolves-to-config | Feed keys have no declared owner, so a workspace can claim a platform key by naming it — [cobenian-accounts#379](https://github.com/Cobenian/cobenian-accounts/issues/379). |

---

## 5. Sources

Written from the implementations rather than from intent, so it can be checked:

- `cobenian-accounts` — `lib/cobenian_accounts/notifications.ex` (`deliver/2`,
  `deliver_to_feed/3`, `resolve_feed/2`), `notifications/notification.ex`,
  `notifications/notification_feed.ex`, `notifications/feeds.ex`,
  `specs/features/accounts/notification-delivery.md`
- `cobenian-foundry` — `apps/comms/lib/comms.ex`, `comms/client.ex`, `comms/message.ex`,
  `comms/dispatcher/router.ex`, `comms/dispatcher/postmark.ex`
