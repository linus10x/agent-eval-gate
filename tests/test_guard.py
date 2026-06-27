"""Deadline cap + fail-closed wrapper. Two strippable POLARITY proofs (G1, G5).

The guard uses an injectable monotonic clock seam and an injectable evaluator
seam, so a slow evaluation is simulated by ADVANCING a fake clock -- no real
sleep, no threads.
"""

import re
from pathlib import Path

from agent_eval_gate.guard import (
    DEFAULT_DEADLINE_S,
    MAX_DEADLINE_S,
    effective_budget,
    guarded_evaluate,
)
from agent_eval_gate.verdict import EvalRequest, EvalVerdict

REPO_ROOT = Path(__file__).resolve().parent.parent
GUARD_PY = REPO_ROOT / "src" / "agent_eval_gate" / "guard.py"


def _req(deadline_s=None):
    return EvalRequest(
        subject="X",
        transfer_seq=10,
        required_sdn_version="2026-06-17",
        screen=None,
        deadline_s=deadline_s,
    )


class _FakeClock:
    """A monotonic clock whose hands a test advances explicitly."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def _allow_verdict():
    return EvalVerdict("ALLOW", None, None, "2026-06-17", {})


def _slow_evaluator(clock, advance_by, inner):
    def _ev(request):
        clock.advance(advance_by)
        return inner
    return _ev


def test_slow_evaluation_denies_within_budget():
    # G1 [POLARITY -- deadline]: a 120s evaluation (over the 90s default budget)
    # whose inner result is ALLOW must be DISCARDED and DENYed. No real sleep.
    # Deliberate break it catches: remove the elapsed>budget DENY block -> RED.
    clock = _FakeClock()
    verdict = guarded_evaluate(
        _req(),
        evaluator=_slow_evaluator(clock, 120.0, _allow_verdict()),
        clock=clock,
    )
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "evaluation_deadline_exceeded"
    assert verdict.rule_cite is None


def test_deadline_capped_at_90():
    # G2: a requested deadline of 300s cannot extend the SLA; 120s > 90 cap -> DENY.
    clock = _FakeClock()
    verdict = guarded_evaluate(
        _req(deadline_s=300.0),
        evaluator=_slow_evaluator(clock, 120.0, _allow_verdict()),
        clock=clock,
    )
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "evaluation_deadline_exceeded"


def test_caller_may_request_less():
    # G3: a tighter caller budget is honored; 20s > 10s requested -> DENY.
    clock = _FakeClock()
    verdict = guarded_evaluate(
        _req(deadline_s=10.0),
        evaluator=_slow_evaluator(clock, 20.0, _allow_verdict()),
        clock=clock,
    )
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "evaluation_deadline_exceeded"


def test_fast_evaluation_passes_through():
    # G4: PRESENCE of ALLOW when under budget -- the deadline must NOT false-DENY.
    clock = _FakeClock()
    inner = _allow_verdict()
    verdict = guarded_evaluate(
        _req(),
        evaluator=_slow_evaluator(clock, 1.0, inner),
        clock=clock,
    )
    assert verdict is inner
    assert verdict.decision == "ALLOW"


def test_exception_in_evaluation_denies():
    # G5 [POLARITY -- fail-closed]: an evaluator that raises must DENY, never
    # propagate and never ALLOW. Deliberate break it catches: remove the
    # try/except-DENY -> the exception propagates -> RED.
    def _boom(request):
        raise RuntimeError("screening provider unreachable")

    clock = _FakeClock()
    verdict = guarded_evaluate(_req(), evaluator=_boom, clock=clock)
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "evaluation_error"
    assert verdict.rule_cite is None


def test_default_budget_is_90():
    # G6: with no deadline_s, 89s passes through, 91s denies. Pins the 90s SLA.
    clock_fast = _FakeClock()
    inner = _allow_verdict()
    ok = guarded_evaluate(_req(), evaluator=_slow_evaluator(clock_fast, 89.0, inner), clock=clock_fast)
    assert ok.decision == "ALLOW"

    clock_slow = _FakeClock()
    over = guarded_evaluate(_req(), evaluator=_slow_evaluator(clock_slow, 91.0, _allow_verdict()), clock=clock_slow)
    assert over.decision == "DENY"
    assert over.failing_assertion == "evaluation_deadline_exceeded"

    assert DEFAULT_DEADLINE_S == 90.0
    assert MAX_DEADLINE_S == 90.0
    assert effective_budget(None) == 90.0
    assert effective_budget(300.0) == 90.0
    assert effective_budget(10.0) == 10.0


def test_guard_emits_no_allow_literal():
    # G7 [STATIC-GUARD]: guard.py hand-writes no ALLOW literal; an ALLOW reaches
    # output only by passing the inner evaluator's verdict through unchanged.
    text = GUARD_PY.read_text()
    assert not re.search(r"""['"]ALLOW['"]""", text), "guard.py must not hand-write an ALLOW literal"
