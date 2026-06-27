"""The GOVERNED inner evaluation. Writes ZERO gate logic.

It maps the request's plain data into the vendored control's ScreenResult, calls
the real FundsGate (NEVER naive_mode), and reads every output field OUT of the
returned GateDecision. No decision string, OFAC cite, or failing assertion is
hand-typed here -- the single source of truth is the vendored gate.
"""

from __future__ import annotations

# Single-line import so the anti-clone static guard (V4) can confirm the reuse.
from agent_funds_gate import FundsGate, GateDecision, OFAC_CITE, ScreenResult, ScreenStatus  # noqa: F401

from .verdict import EvalRequest, EvalVerdict


def _build_screen(data: dict | None) -> ScreenResult | None:
    """Map plain screen data into the vendored ScreenResult, or None.

    The status-string -> ScreenStatus map is the only construction step;
    server.validate_arguments has already rejected an unknown status enum, so an
    unrecognized status never reaches here. Building a ScreenResult is allowed;
    deciding on it is the gate's job, not ours.
    """
    if data is None:
        return None
    return ScreenResult(
        status=ScreenStatus(data["status"]),
        sdn_list_version=data["sdn_list_version"],
        completed_seq=data["completed_seq"],
        subject=data["subject"],
    )


def evaluate(request: EvalRequest) -> EvalVerdict:
    """Run the request through the real, governed gate and read out its verdict."""
    screen = _build_screen(request.screen)
    decision: GateDecision = FundsGate(request.required_sdn_version).authorize(
        subject=request.subject,
        transfer_seq=request.transfer_seq,
        screen=screen,
    )
    return EvalVerdict(
        decision=decision.decision,
        rule_cite=decision.rule_cite,
        failing_assertion=decision.failing_assertion,
        sdn_list_version=decision.sdn_list_version,
        evidence=decision.evidence,
    )
