"""Governed evaluation core: gate-path correctness, derived fields, anti-defeat.

Every assertion checks the PRESENCE of the safe condition (a real DENY or a real
ALLOW read out of the vendored gate), never merely the absence of something.
"""

import re
from pathlib import Path

from agent_funds_gate import FundsGate, GateDecision, OFAC_CITE, ScreenResult, ScreenStatus

from agent_eval_gate.evaluate import evaluate
from agent_eval_gate.verdict import EvalRequest

REPO_ROOT = Path(__file__).resolve().parent.parent
EVALUATE_PY = REPO_ROOT / "src" / "agent_eval_gate" / "evaluate.py"

_SDN_VERSION = "2026-06-17"
_SUBJECT = "BLOCKED PERSON ALPHA"


def _req(*, subject=_SUBJECT, transfer_seq=10, required_sdn_version=_SDN_VERSION,
         screen="default", deadline_s=None):
    if screen == "default":
        screen = {
            "status": "clear",
            "sdn_list_version": _SDN_VERSION,
            "completed_seq": 15,
            "subject": _SUBJECT,
        }
    return EvalRequest(
        subject=subject,
        transfer_seq=transfer_seq,
        required_sdn_version=required_sdn_version,
        screen=screen,
        deadline_s=deadline_s,
    )


def test_governed_race_denies_on_ordering():
    # E1: CLEAR screen completes at seq 15, AFTER the transfer at seq 10.
    verdict = evaluate(_req())
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "screen_completion_precedes_execution"
    assert verdict.rule_cite == OFAC_CITE


def test_safe_scenario_allows():
    # E2: PRESENCE of the safe ALLOW -- guards against a deny-everything false pass.
    screen = {"status": "clear", "sdn_list_version": _SDN_VERSION,
              "completed_seq": 5, "subject": _SUBJECT}
    verdict = evaluate(_req(screen=screen))
    assert verdict.decision == "ALLOW"
    assert verdict.rule_cite is None
    assert verdict.failing_assertion is None


def test_verdict_fields_read_from_gatedecision():
    # E3: truthfulness/single-source -- the verdict fields equal the real
    # GateDecision fields, proving they are derived and not hand-typed.
    race_screen = ScreenResult(ScreenStatus.CLEAR, _SDN_VERSION, completed_seq=15, subject=_SUBJECT)
    gate_race = FundsGate(_SDN_VERSION).authorize(subject=_SUBJECT, transfer_seq=10, screen=race_screen)
    race_verdict = evaluate(_req())
    assert race_verdict.rule_cite == gate_race.rule_cite == OFAC_CITE
    assert race_verdict.failing_assertion == gate_race.failing_assertion

    safe_screen_data = {"status": "clear", "sdn_list_version": _SDN_VERSION,
                        "completed_seq": 5, "subject": _SUBJECT}
    safe_screen = ScreenResult(ScreenStatus.CLEAR, _SDN_VERSION, completed_seq=5, subject=_SUBJECT)
    gate_safe = FundsGate(_SDN_VERSION).authorize(subject=_SUBJECT, transfer_seq=10, screen=safe_screen)
    safe_verdict = evaluate(_req(screen=safe_screen_data))
    assert safe_verdict.rule_cite is gate_safe.rule_cite is None
    assert safe_verdict.failing_assertion is gate_safe.failing_assertion is None


def test_missing_screen_denies():
    # E4
    verdict = evaluate(_req(screen=None))
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "screen_present"


def test_hit_screen_denies():
    # E5
    screen = {"status": "hit", "sdn_list_version": _SDN_VERSION,
              "completed_seq": 5, "subject": _SUBJECT}
    verdict = evaluate(_req(screen=screen))
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "sdn_hit"


def test_subject_mismatch_denies():
    # E6
    screen = {"status": "clear", "sdn_list_version": _SDN_VERSION,
              "completed_seq": 5, "subject": "SOMEONE ELSE"}
    verdict = evaluate(_req(screen=screen))
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "screen_subject_mismatch"


def test_version_mismatch_denies():
    # E7
    screen = {"status": "clear", "sdn_list_version": "2026-01-01",
              "completed_seq": 5, "subject": _SUBJECT}
    verdict = evaluate(_req(screen=screen))
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "sdn_version_pinned"


def test_pending_screen_denies():
    # E8
    screen = {"status": "pending", "sdn_list_version": _SDN_VERSION,
              "completed_seq": None, "subject": _SUBJECT}
    verdict = evaluate(_req(screen=screen))
    assert verdict.decision == "DENY"
    assert verdict.failing_assertion == "screen_completion_precedes_execution"


def test_evaluate_never_constructs_naive_gate():
    # E9 [STATIC-GUARD]: behavioral -- the race ALWAYS denies through evaluate;
    # static -- naive_mode=True appears nowhere in evaluate.py.
    for _ in range(3):
        assert evaluate(_req()).decision == "DENY"
    text = EVALUATE_PY.read_text()
    assert not re.search(r"naive_mode\s*=\s*True", text), "evaluate.py must never build a naive gate"
