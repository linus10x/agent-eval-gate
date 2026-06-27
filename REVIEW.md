# Code review: agent-eval-gate (MCP OFAC eval-gate server)

Reviewer: code-reviewer subagent (A2), adversarial / fail-closed.
Date: 2026-06-27
Verdict: **PASS-WITH-FIXES**

Default posture is REJECT; this artifact earns a conditional pass because every
fail-closed safety property is genuinely enforced (re-proven below), no path to a
false ALLOW was found, no gate logic leaks into `src/`, and the anti-clone /
anti-defeat statics are honest. One MAJOR boundary/resilience defect (non-dict
`params` crashes the serve loop) and three accepted deviations are recorded. The
MAJOR is fail-closed (never ALLOW; process exits 5) so it does NOT meet the FAIL
bar (no false-pass on the sanctions control), but it contradicts the dispatcher's
own "never raises" contract and the plan's DENY-vs-error boundary and should be
fixed before this is reused as the template for the fail-closed safety family.

---

## Evidence: the four polarity re-proofs (caches off, PYTHONDONTWRITEBYTECODE=1)

Baseline: `48 passed in 0.27s`.

1. **S4 / E1 centerpiece (gate naive).** Patched `evaluate.py` to
   `FundsGate(..., naive_mode=True)`:
   - `test_centerpiece_race_denies_through_tool_call` -> RED (`'ALLOW' == 'DENY'`)
   - `test_governed_race_denies_on_ordering` -> RED (`'ALLOW' == 'DENY'`)
   - Restored -> both green.
   The assertion checks PRESENCE of the safe DENY: `decision == "DENY"` AND
   `rule_cite == OFAC_CITE` AND `failing_assertion == "screen_completion_precedes_execution"`
   AND `isError is False`. Not a "!= ALLOW" check. Genuine.

2. **G1 deadline.** Deleted the `elapsed > budget -> DENY` block in `guard.py`:
   - `test_slow_evaluation_denies_within_budget` -> RED (`'ALLOW' == 'DENY'`)
   - Restored -> green. Asserts `decision=="DENY"` AND
     `failing_assertion=="evaluation_deadline_exceeded"` AND `rule_cite is None`,
     with an inner ALLOW that must be DISCARDED. Genuine.

3. **G5 fail-closed.** Deleted the `try/except -> DENY` in `guard.py`:
   - `test_exception_in_evaluation_denies` -> RED (`RuntimeError` propagates)
   - Restored -> green. Asserts `decision=="DENY"` AND
     `failing_assertion=="evaluation_error"`. Genuine.

4. **V1 vendor drift.** Appended `\n# drift\n` to `vendor/agent_funds_gate/gate.py`:
   - `test_vendored_gate_matches_pinned_digests` -> RED (digest mismatch)
   - `check_vendor_integrity()` -> `False` (startup would exit 4; per-call DENY via S14)
   - Restored -> green; `check_vendor_integrity()` -> `True`.

All four guards go RED on their named break and green on restore: none are
decorative. After restore, the four vendored SHA-256 digests recompute equal to
VENDOR.md, and the full suite is `48 passed` with caches off.

## Evidence: clone-to-green / no-install / no-network

- `rsync` copy to `/tmp/aeg-clone` (no `.git`, no caches); from the COPY:
  `demo.sh exit=0`; `serve.sh` race -> `structuredContent.decision="DENY"`,
  `isError:false`, exit 0. No pip install.
- `serve.sh` / `demo.sh` are `PYTHONPATH=...src:...vendor` exec wrappers (not bare
  `python3 -m`). D1/D3/D4 disable `socket.socket` via sitecustomize and still pass.
- `demo.sh` transcript carries the framing law ("we attacked our own gate and it
  holds", "the under-governed agent would ALLOW this; the governed gate DENYs it")
  and never prints "caught a real incident".

## Evidence: no false ALLOW / injection / honesty

- ALLOW is reachable only out of a real `GateDecision` through `evaluate`, and only
  if `guarded_evaluate` finds `elapsed <= budget`; over-budget and exception both
  discard/replace with a DENY. No hand-written quoted `ALLOW` in `src/` (V6 + grep
  confirm; the only "ALLOW" tokens are unquoted prose in TOOL_DESCRIPTION/demo).
- Negative/zero seq, bool seq, bool completed_seq, string seq, float seq, unknown
  status enum, unknown tool, extra fields: each is rejected as `-32602` or denied
  by the gate; none produced an ALLOW-shaped success.
- S16 injection: `__import__('os').system('rm -rf /')` flows as inert data;
  `evidence.subject == payload`; no eval/exec/__import__/subprocess/socket and no
  write-mode `open` exists anywhere in `src/` (grep clean).

---

## Findings

### MAJOR-1 — A non-dict `params` raises out of the dispatcher and crashes the serve loop
File: `src/agent_eval_gate/server.py:230` (`initialize`), `:246` and
`_handle_tool_call:186` (`tools/call`).

`handle_request` does `(request.get("params") or {}).get(...)` for `initialize`
and passes `request.get("params") or {}` straight into `_handle_tool_call`, which
calls `params.get("name")`. JSON-RPC 2.0 permits `params` to be a structured value
(array OR object), so `"params": [..]` or `"params": "x"` is a client input, not an
impossibility. Observed:

```
tools/call params=list  -> RAISED AttributeError: 'list' object has no attribute 'get'
initialize params=list   -> RAISED AttributeError: 'list' object has no attribute 'get'
serve() over [bad-params msg, valid initialize] -> RAISED, out=''  (initialize NEVER answered)
bash serve.sh <same>     -> "INTERNAL ERROR: AttributeError(...)"; exit=5
```

Impact: one wrong-typed `params` message kills the entire loop and drops every
subsequent message (a parse error recovers per L4; a wrong-typed params does not).
This contradicts (a) the `handle_request` docstring "Never raises out on a
tools/call" (server.py:217), (b) plan 4.7 "malformed envelope ... -> a JSON-RPC
error", and (c) the L4 resilience intent. It is fail-closed at the process layer
(exit 5, never ALLOW), so it is NOT a sanctions false-pass and not a FAIL gate, but
it is a real boundary + availability defect.

Minimal fix (either, prefer both):
- In `handle_request`, after computing `method`, coerce/validate params: if
  `request.get("params")` is present and not a dict, return
  `_error(rid, _INVALID_REQUEST, "params must be an object")` (or `-32602` on
  tools/call) instead of dispatching.
- Defensively wrap the `handle_request(msg, state)` call in `serve()` with
  `try/except Exception` that writes an internal-error response (echoing `msg`'s id
  when available) and `continue`s, so no single message can wedge the loop.
- Add a test (S-series): `tools/call`/`initialize` with `params` as a list/string ->
  a JSON-RPC error response (not a raise), and a serve-loop test that a bad-params
  line is followed by a successfully answered initialize (the L4 analogue).

### MINOR-1 (accepted) — demo safe-case is a presence check, not `== "ALLOW"`
File: `src/agent_eval_gate/demo.py:91`. `decision != "DENY" and rule_cite is None
and failing_assertion is None`. Accepted: `demo.py` lives under `src/` and V6 bans a
quoted `ALLOW` literal there, so `== "ALLOW"` is not available. The check is still a
positive-shape assertion — both safe fields must be None, a shape only a real gate
ALLOW yields (a wrapper DENY sets `failing_assertion`; a gate DENY sets both). D2
additionally asserts the demo OUTPUT contains the safe ALLOW and exits 0 only when
`ok_safe` holds. Adequate; not weakened in a way that false-passes.

### MINOR-2 (accepted) — lazy `__init__` (PEP 562 `__getattr__`)
File: `src/agent_eval_gate/__init__.py:31`. Defers `server.py` import. Does not hide
an import error: `server.py` is imported directly by `demo.py` and by the tests
(`from agent_eval_gate import server`), so any failure surfaces. Accepted.

### MINOR-3 (accepted) — added `src/agent_eval_gate/demo.py`
In scope (the plan's demo.sh logic factored into a module). Beneficial: it is now
covered by the V4/V5/V6 static guards (rglob over `src/`) and exercised by D2.
Accepted.

### INFO — honest, well-built items worth recording
- evaluate.py reads ALL output fields out of the real `GateDecision`; nothing is
  re-typed (E3 cross-checks against a directly-constructed gate decision).
- Wrapper DENYs correctly carry `rule_cite=None` (deadline/error/vendor) so the OFAC
  cite is never misattributed; gate DENYs carry the real cite.
- bool-as-int trap is handled at BOTH layers (validate_arguments + the vendored gate).
- README/CONTROL_INDEX are pure ASCII, no banned AI-tell terms, no proprietary
  system names, framing law correct.

---

## Gate-by-gate
- Centerpiece polarity (S4): PASS (re-proven RED-on-break).
- Deadline polarity (G1) + non-extendable cap (G2/G6): PASS.
- Error->DENY polarity (G5): PASS.
- Vendor drift (V1/V7/S14): PASS (startup exit 4 + per-call DENY).
- No gate logic in src (V4/V5/V6): PASS (honest; grep-confirmed).
- DENY-vs-error boundary (4.7): PASS for typed-unsafe vs typed-fault; **gap** on a
  wrong-TYPED `params` value (MAJOR-1) — crashes instead of erroring (fail-closed).
- Injection / no side effects (S16): PASS.
- Clone-to-green / no-network (D1-D4): PASS.
- Prose firewall: PASS.

## Restoration
All four temporary polarity breaks restored. `git`: not a repo (no diffs to leak).
Vendored digests recomputed == VENDOR.md. Final: `48 passed in 0.26s`, caches off.
