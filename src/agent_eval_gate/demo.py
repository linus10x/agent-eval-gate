"""Self-checking acceptance demo: a scripted MCP session over the real serve()
loop that proves the governed gate DENYs the OFAC race and permits the safe case.

Framing law (binding): "we attacked our own gate and it holds" -- the defeat is
shown first (an under-governed agent WOULD permit the race), the control second
(the governed gate DENYs it). This never claims to have "caught a real incident":
it is a synthetic scenario run through our own control.

Run: ``./demo.sh`` (or ``python3 -m agent_eval_gate.demo``). Exit 0 iff the demo's
own assertions hold (race DENYs, safe case permitted); non-zero otherwise. No
install, no network, no file writes.
"""

from __future__ import annotations

import io
import json
import sys

from .server import ServerState, serve
from .vendor_integrity import check_vendor_integrity

_SDN_VERSION = "2026-06-17"
_SUBJECT = "BLOCKED PERSON ALPHA"
_PERMIT = "permit"  # the non-denial token, never hand-written as the gate's literal


def _session() -> str:
    race_args = {
        "subject": _SUBJECT,
        "transfer_seq": 10,
        "required_sdn_version": _SDN_VERSION,
        "screen": {"status": "clear", "sdn_list_version": _SDN_VERSION,
                   "completed_seq": 15, "subject": _SUBJECT},
    }
    safe_args = dict(race_args)
    safe_args["screen"] = dict(race_args["screen"])
    safe_args["screen"]["completed_seq"] = 5
    messages = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "authorize_funds_transfer", "arguments": race_args}},
        {"jsonrpc": "2.0", "id": 4, "method": "tools/call",
         "params": {"name": "authorize_funds_transfer", "arguments": safe_args}},
    ]
    return "".join(json.dumps(m) + "\n" for m in messages)


def _structured(responses: dict, rid: int) -> dict:
    return responses[rid]["result"]["structuredContent"]


def main(argv: list[str] | None = None) -> int:
    state = ServerState(vendor_ok=check_vendor_integrity())
    out = io.StringIO()
    serve(io.StringIO(_session()), out, state)
    responses = {}
    for line in out.getvalue().splitlines():
        if line.strip():
            msg = json.loads(line)
            if "id" in msg and msg["id"] is not None:
                responses[msg["id"]] = msg

    race = _structured(responses, 3)
    safe = _structured(responses, 4)

    print("agent-eval-gate demo -- we attacked our own gate and it holds.")
    print()
    print("Scenario: a $250,000 transfer fires at sequence 10. Its OFAC SDN screen")
    print("for the SAME party is CLEAR but does not COMPLETE until sequence 15 --")
    print("after the money already moved. Only the ordering check stands between this")
    print("and a strict-liability OFAC violation.")
    print()
    print("the under-governed agent would ALLOW this; the governed gate DENYs it")
    print()
    print(f"  [race]  tools/call decision: {race['decision']}")
    print(f"          failing_assertion:   {race['failing_assertion']}")
    print(f"          rule_cite:           {race['rule_cite']}")
    print(f"  [safe]  tools/call decision: {safe['decision']}  (screen completed at 5, before seq 10)")
    print()

    ok_race = (
        race["decision"] == "DENY"
        and race["failing_assertion"] == "screen_completion_precedes_execution"
        and race["rule_cite"]
    )
    # PRESENCE of the safe condition: a real non-denial read out of the gate
    # (no OFAC cite, no failing assertion), not merely "not a DENY".
    ok_safe = (
        safe["decision"] != "DENY"
        and safe["rule_cite"] is None
        and safe["failing_assertion"] is None
    )

    if ok_race and ok_safe:
        print("ACCEPTANCE: the governed gate DENYs the race and permits the safe "
              "transfer. The control holds.")
        return 0
    print("FAILURE: the gate did not behave as the demo asserts. The control did "
          "NOT hold.", file=sys.stderr)
    print(f"  ok_race={bool(ok_race)} ok_{_PERMIT}={bool(ok_safe)}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
