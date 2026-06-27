"""Pure request/verdict types. NO gate import here.

Keeping these free of the vendored control lets guard.py and server.py build
wrapper-level DENY verdicts (deadline / error / vendor-drift) without importing
the gate -- those wrapper DENYs are server-owned and carry rule_cite=None, since
the gate did not render them and misattributing the OFAC cite would be dishonest.
A gate-rendered verdict reads its fields out of a real GateDecision (see
evaluate.py); this module never decides anything.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class EvalRequest:
    """A funds-transfer authorization request, as plain data.

    ``screen`` is plain data ({status, sdn_list_version, completed_seq, subject})
    or None; it is mapped to a ScreenResult only inside evaluate.py. ``deadline_s``
    is the caller-requested budget (None -> default); the guard caps it at 90.
    """

    subject: str
    transfer_seq: int
    required_sdn_version: str
    screen: dict | None
    deadline_s: float | None


@dataclass(frozen=True)
class EvalVerdict:
    """The structured verdict returned to the MCP client.

    ``decision`` is the gate's allow-or-deny token. An allow is ONLY ever read out
    of a real GateDecision (evaluate.py); no module hand-writes that token.
    Wrapper-level denials carry rule_cite=None; gate-rendered denials carry the
    real OFAC cite/assertion.
    """

    decision: str
    rule_cite: str | None
    failing_assertion: str | None
    sdn_list_version: str | None
    evidence: dict
