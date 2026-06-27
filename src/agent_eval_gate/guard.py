"""Fail-closed wrapper around the governed evaluation.

Two server-level promises the bare control lacks, each with a strippable
polarity proof:
  - a NON-EXTENDABLE deadline (a caller may request less than 90s, never more);
    over budget -> the inner result is discarded and the call DENYs.
  - error -> DENY (any exception in the evaluation becomes a DENY, never raises
    and never ALLOWs).

The deadline is a post-hoc elapsed check around an injectable monotonic clock
and an injectable evaluator: a test advances a FAKE clock to simulate a slow
evaluation with no real sleep and no threads. The inner evaluation is pure,
synchronous CPU (a dict -> gate call) that cannot be pre-empted mid-call, so
"deny within deadline" is a bounded-report guarantee (a result that took longer
than the SLA is discarded), not a pre-emptive kill. On Mac sleep, time.monotonic
advances past the budget on resume, so an interrupted call DENYs -- fail closed.
"""

from __future__ import annotations

import time
from typing import Callable

from .evaluate import evaluate
from .verdict import EvalRequest, EvalVerdict

DEFAULT_DEADLINE_S = 90.0
MAX_DEADLINE_S = 90.0  # the safety SLA: a caller may request LESS, never MORE.


def effective_budget(requested: float | None) -> float:
    """None -> the default; otherwise the smaller of the request and the 90s cap.

    (requested <= 0 is rejected earlier in validate_arguments; the cap is here.)
    """
    if requested is None:
        return DEFAULT_DEADLINE_S
    return min(requested, MAX_DEADLINE_S)


def guarded_evaluate(
    request: EvalRequest,
    *,
    evaluator: Callable[[EvalRequest], EvalVerdict] = evaluate,
    clock: Callable[[], float] = time.monotonic,
) -> EvalVerdict:
    budget = effective_budget(request.deadline_s)
    t0 = clock()
    try:
        inner = evaluator(request)
    except Exception:
        # FAIL-CLOSED: any error -> DENY, never raise, never pass through.
        return EvalVerdict(
            decision="DENY",
            rule_cite=None,
            failing_assertion="evaluation_error",
            sdn_list_version=None,
            evidence={"wrapper": "guard", "reason": "evaluation_error"},
        )
    elapsed = clock() - t0
    if elapsed > budget:
        # DEADLINE: over budget -> discard the inner result and DENY.
        return EvalVerdict(
            decision="DENY",
            rule_cite=None,
            failing_assertion="evaluation_deadline_exceeded",
            sdn_list_version=None,
            evidence={"wrapper": "guard", "budget_s": budget, "elapsed_s": elapsed},
        )
    return inner
