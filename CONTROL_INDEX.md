# Control index

One row: the tool, the control it exposes, the reg anchor, and what it does NOT
catch. v1 exposes exactly one tool over MCP, wrapping the single vendored control.
The scope limits below are inherited from the vendored control; they are linked
here, not restated, so the two never drift.

| tool | control | reg anchor | status |
|---|---|---|---|
| `authorize_funds_transfer` | OFAC screen-before-transfer gate (a version-pinned SDN screen must return CLEAR and COMPLETE before the transfer executes) | 31 CFR 501.603 (block SDN property) / 501.604 (reject prohibited transfer); strict liability under IEEPA, 50 U.S.C. 1705 | SHIPPED (v1) |

The reg cite and the failing assertion in every DENY are read out of the real
`GateDecision` (the vendored `OFAC_CITE` and `screen_completion_precedes_execution`
strings); they are never re-typed in this index or in `src/`. The single source of
truth for the control's scope is the vendored gate source under
`vendor/agent_funds_gate/`, with provenance and pinned digests in `vendor/VENDOR.md`.

## What this tool does NOT catch (inherited scope limits of the vendored control)

- No name or fuzzy matching against the SDN list. The screen result is taken as
  given data; the gate enforces ORDERING and binding, not the match itself.
- No 50%-rule (OFAC ownership aggregation) logic.
- No license / general-license evaluation.
- No signed-screen or screen-provenance verification. A screen result is trusted
  as supplied; the gate does not authenticate who produced it.
- One subject, one transfer, one screen per call. No batching, no multi-party
  settlement, no netting.

## What the server ADDS around the control (and its own limits)

- An MCP / JSON-RPC 2.0 stdio transport (stdlib only).
- A non-extendable deadline (a caller may request less than 90 seconds, never
  more; over budget denies) and an error-to-DENY wrapper. Both are post-hoc,
  synchronous checks around a pure evaluation: the deadline is a bounded-report
  guarantee (a too-slow result is discarded), not a pre-emptive kill.
- A startup and per-call vendor-integrity refusal: a drifted vendored control
  makes the server refuse to serve (exit 4) and makes every tool call DENY
  (`vendor_integrity_failure`).
- No second tool, no LLM call, no network, no persisted state, no publish or send.

## Extension contract

A new control is a new tool with its own vendored source, its own pinned digests,
and its own polarity proof. It is not added by editing the vendored gate. v1 ships
one tool; nothing here is a roadmap promise.
