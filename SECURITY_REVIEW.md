# Security review - agent-eval-gate

Date: 2026-06-27. Independent security pass (separate from the functional
code-review in REVIEW.md), per the Track B rule that a literal security-review
runs on a fail-closed safety surface (a false-pass ships an OFAC-screening
defect).

## Verdict: NO qualifying HIGH/MEDIUM vulnerabilities (confidence >= 8/10).

Every MCP tool argument (`subject`, `transfer_seq`, `required_sdn_version`,
`screen{...}`, `deadline_s`) and the raw stdin JSON were traced from input to
every sink. The surface is closed:

- **Arguments are data-only.** `validate_arguments` rejects unknown top-level and
  unknown `screen` keys (hand-enforced `additionalProperties`) and type-checks
  each field (strings stay strings; ints exclude bool). Validated fields are
  copied 1:1 into the vendored `FundsGate.authorize(...)`. No key-driven object
  construction, no getattr/setattr-by-name on input, no format-string/template
  sink. A `subject` of `"__import__('os').system(...)"` is just a string the gate
  compares for equality.
- **No dynamic-execution or deserialization sinks.** `json.loads` is the only
  parser; no pickle/marshal/yaml/eval/exec/compile/`__import__`-by-name in src/.
  The single `getattr` (`__init__.py`) is gated to a fixed three-name allowlist.
  `ScreenStatus(data["status"])` is an enum value lookup already constrained to
  clear|hit|pending|error by validation.
- **No argument reaches a filesystem path.** The only file I/O is
  `vendor_integrity.py` reading the vendored files + VENDOR.md from paths derived
  from `__file__`; `main()` calls `check_vendor_integrity()` with no arguments, so
  no tool argument can redirect those paths. Zero runtime writes, network calls,
  or subprocess invocations.
- **No false-ALLOW / authorization-bypass path.** `naive_mode` is not an accepted
  argument (rejected as unknown) and is never passed by the wrapper; the ALLOW
  token is never hand-written in src/ (read out of a real `GateDecision`), so the
  wrapper cannot synthesize an ALLOW. Both wrappers default to DENY: vendor drift
  forces a per-call DENY and refuses to serve at startup (exit 4); any evaluator
  exception or deadline overage discards the inner result and returns DENY; the
  serve loop's catch-all reports an internal error, never an ALLOW.
- **No data exposure.** No secrets/PII/credentials in the codebase; evidence dicts
  echo only the caller's own supplied fields.
- **Shell wrappers** set a static PYTHONPATH and `exec python3 -m ...` with no
  interpolation of untrusted input (`"$@"` is the local operator's argv, not
  MCP-client data). No command-injection path (shell-script precedent).

The surface matches the design: arguments are inert data, the default decision is
DENY, and the only security-relevant decision is delegated unchanged to the
pinned, integrity-checked vendored control.
