# agent-eval-gate

An MCP (Model Context Protocol) server, over stdio, that exposes one OFAC
screen-before-transfer control as a single callable tool. An MCP client calls
`authorize_funds_transfer` and gets the gate's structured verdict: a
transfer is permitted only if a version-pinned OFAC SDN screen returned CLEAR and
COMPLETED before the transfer executed. Every other ordering is denied.

The server wraps that vendored control
(`agent-funds-gate`, under `vendor/`). It is not a new control and not a
generic agent framework. `./demo.sh` checks one denied race and one permitted case.

## The one command

Serve the tool over stdio:

```
./serve.sh
```

See the acceptance demo (self-checking; exit 0 only if the race is
denied and the safe case is permitted):

```
./demo.sh
```

Both are PYTHONPATH-setting wrappers around `python3 -m ...`. No install, no
network, no `make`. They read only the in-tree `src` and `vendor` files.

## What it ADDS vs what it REUSES

REUSES (verbatim, vendored, unchanged): the `FundsGate` ordering enforcement and
its `naive_mode` defeat; `ScreenResult`, `ScreenStatus`, `GateDecision`, the
`OFAC_CITE` string, and the `screen_completion_precedes_execution` assertion. The
server writes zero gate logic and imports the real public surface. See
`vendor/VENDOR.md` for the pinned commit and per-file digests.

ADDS: an MCP / JSON-RPC 2.0 stdio transport (stdlib only) so a real MCP client
can call the control; two server-level fail-closed promises the bare control
lacks, each with a strippable polarity proof:

1. a non-extendable deadline. A caller may request a tighter budget; it can never
   request more than 90 seconds. If the evaluation runs longer than the budget,
   its result is discarded and the call denies. (If the machine sleeps mid-call,
   the monotonic clock advances past the budget on resume, so the call denies.)
2. error to DENY. Any exception inside the evaluation becomes a DENY; it never
   raises out and never permits.

It also adds a startup and per-call vendor-integrity refusal, and one-command,
zero-install, no-network packaging.

The split: `agent-funds-gate` implements the control; `agent-eval-gate` makes it
callable as a governed MCP tool with a deadline-bounded, fail-closed wrapper.

## Example scenario

The scenario the demo runs: a $250,000 transfer fires at sequence 10. Its OFAC
SDN screen for the same party is CLEAR but does not complete until sequence 15 --
after the money already moved. An under-governed agent (ordering check stripped)
would permit this race; the governed gate denies it, naming the OFAC reg cite and
the failing assertion `screen_completion_precedes_execution`, both read out of the
real gate decision and never re-typed. This is a synthetic scenario run through
our own control, not a real incident.

## DENY vs error

A well-typed but unsafe scenario (the race, an SDN hit, a pending screen, a
missing screen, a subject mismatch, a version mismatch) is a SUCCESSFUL tool
result with `structuredContent.decision = "DENY"` and `isError = false`. A DENY
is not a JSON-RPC error.

A protocol or argument fault (a missing required argument, a wrong JSON type, an
unknown status enum, an unknown tool name, a malformed envelope, an unknown
method, an unparseable line) is a JSON-RPC error object. A missing or null
`screen` is not a fault; it is a safe DENY (`screen_present`).

A `deadline_s` greater than 90 is not an error. The guard silently caps the
effective budget at 90; the SLA is not caller-extendable.

## Exit-code contract

Server process (`serve.sh`):

| code | meaning |
|---|---|
| 0 | clean shutdown on stdin EOF after serving |
| 4 | vendored-gate integrity check failed at startup; the server refused to serve |
| 5 | unhandled fatal around the loop (fail closed; never 0 on a crash) |

JSON-RPC error codes inside the protocol: -32700 parse error, -32600 invalid
request, -32601 method not found, -32602 invalid params. A tool DENY is a
successful result, never an error object.

Demo process (`demo.sh`): 0 only if its own assertions hold (the race denied and
the safe case permitted); non-zero if they do not. The demo is a self-checking
acceptance gate, not just a print.

## Injection posture

Tool-call arguments arrive from an MCP client that may be an under-governed agent.
Every argument is treated as data. An argument only populates the `subject`,
`transfer_seq`, `required_sdn_version`, and `screen` values handed to the gate.
An argument can never select a code path, name a module to import, evaluate a
string, trigger a file write, a network call, or a spend. A `subject` of
`"__import__('os').system('rm -rf /')"` is an inert string the gate decides on by
its ordering invariant alone. This is asserted by test (S16).

## Scope limits

All scope limits of the vendored control stand and are linked, not restated, from
`CONTROL_INDEX.md`. No new control, no second tool, no name or fuzzy matching, no
50%-rule, no license logic, no signed-screen verification. No external MCP SDK, no
jsonschema lib, no network, no install step, no `make`, no Docker, no LLM calls,
no agent runtime, no dashboard, and no publish, send, or spend step. stdio only.
The server terminates at an MCP client reading a structured verdict.

## How it stays honest

The server writes zero gate logic. Static tests assert that `src/` defines no
`class FundsGate`, no `def authorize`, no `completed_seq` comparison, no
`naive_mode=True`, and no hand-written allow literal. The only permit reaching
output is read out of a real `GateDecision`. The vendored control is pinned by
per-file SHA-256; silent drift turns the suite red and makes the server refuse to
serve. Run the full suite with `python3 -m pytest -q`.

## License

MIT for the server's own wrapper code (see `LICENSE`). The vendored control is
reused upstream IP under MIT; see `vendor/VENDOR.md`.
