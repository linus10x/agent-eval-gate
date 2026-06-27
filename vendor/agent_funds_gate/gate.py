from __future__ import annotations

from .decision import GateDecision
from .screening import ScreenResult, ScreenStatus

# Precise anchor pulled from the canonical reg SSOT (active_regs.yaml:
# ofac_sdn_screening) and verified against eCFR/OFAC primary sources: a prohibited
# transfer to an SDN must be blocked (31 CFR 501.603) or rejected (31 CFR 501.604)
# before value moves, and civil liability is STRICT under IEEPA (50 U.S.C. 1705)
# regardless of intent. The strict-liability standard is why a screen that merely
# *exists* is not enough -- it must complete before the transfer, or you are liable.
OFAC_CITE = (
    "31 CFR 501.603 (block SDN property) / 501.604 (reject prohibited transfer); "
    "strict liability under IEEPA, 50 U.S.C. 1705"
)

# The single invariant that defines this gate: the screen must have COMPLETED
# (terminal, with a sequence number) strictly BEFORE the transfer executed.
ORDERING_ASSERTION = "screen_completion_precedes_execution"


class FundsGate:
    """Fail-closed authorization gate for value-moving agent actions.

    A transfer is ALLOWed only if a version-pinned OFAC SDN screen returned
    CLEAR *and completed before* the transfer executed. ``naive_mode=True``
    strips the ordering enforcement to reproduce the false-pass the gate exists
    to prevent.
    """

    def __init__(self, required_sdn_version: str, *, naive_mode: bool = False):
        self.required_sdn_version = required_sdn_version
        self.naive_mode = naive_mode

    def authorize(
        self, *, subject: str, transfer_seq: int, screen: ScreenResult | None
    ) -> GateDecision:
        # Validate input SHAPE first. A fail-closed control denies malformed
        # input; it must never raise (an exception in a "should I block?" check
        # can be swallowed by the caller and resolve to "proceed"). bool is an
        # int subtype in Python (True == 1), so exclude it explicitly.
        if not isinstance(transfer_seq, int) or isinstance(transfer_seq, bool):
            return self._deny_bare("transfer_seq_invalid", subject, transfer_seq)
        if screen is not None and not isinstance(screen, ScreenResult):
            return self._deny_bare("screen_malformed", subject, transfer_seq)

        evidence = {
            "subject": subject,
            "transfer_seq": transfer_seq,
            "screen_status": screen.status.value if screen else None,
            "completed_seq": screen.completed_seq if screen else None,
            "sdn_list_version": screen.sdn_list_version if screen else None,
            "naive_mode": self.naive_mode,
        }

        # The defeat: a naive check only asks "did a clear screen exist?" and
        # ignores whether it completed before the money moved. This is the hole.
        if self.naive_mode:
            if screen is not None and screen.status is ScreenStatus.CLEAR:
                return self._allow(screen, evidence)
            return self._deny("naive_no_clear_screen", screen, evidence)

        # Enforced: every condition must hold, in order, or the transfer is denied.
        if screen is None:
            return self._deny("screen_present", screen, evidence)
        if screen.status is ScreenStatus.HIT:
            return self._deny("sdn_hit", screen, evidence)
        if screen.status is ScreenStatus.ERROR:
            return self._deny("screen_error", screen, evidence)
        # The screen must be ABOUT the party being paid. The gate takes the
        # subject separately from the screen, so an unbound clean screen of a
        # different party would otherwise authorize a sanctioned payment.
        if screen.subject != subject:
            return self._deny("screen_subject_mismatch", screen, evidence)
        if screen.completed_seq is None or screen.completed_seq >= transfer_seq:
            # PENDING (no completed_seq) or completed after the transfer fired.
            return self._deny(ORDERING_ASSERTION, screen, evidence)
        # Sequence values are positions of a monotonic counter at execution.
        # Negative/zero values are uninitialized or spoofed -> fail closed.
        if transfer_seq <= 0 or screen.completed_seq <= 0:
            return self._deny("seq_out_of_range", screen, evidence)
        if screen.sdn_list_version != self.required_sdn_version:
            return self._deny("sdn_version_pinned", screen, evidence)
        # Affirm the one safe status POSITIVELY, rather than reaching ALLOW by
        # falling through the HIT/ERROR special-cases. Catches an inconsistent
        # PENDING-with-seq result and any ScreenStatus member added later.
        if screen.status is not ScreenStatus.CLEAR:
            return self._deny("screen_not_clear", screen, evidence)
        return self._allow(screen, evidence)

    def _allow(self, screen: ScreenResult, evidence: dict) -> GateDecision:
        return GateDecision(
            decision="ALLOW",
            rule_cite=None,
            failing_assertion=None,
            sdn_list_version=screen.sdn_list_version,
            evidence=evidence,
        )

    def _deny_bare(
        self, failing_assertion: str, subject: str, transfer_seq: object
    ) -> GateDecision:
        """Deny on malformed input, before a full evidence dict can be built
        from an object the gate cannot trust to have the expected fields."""
        return GateDecision(
            decision="DENY",
            rule_cite=OFAC_CITE,
            failing_assertion=failing_assertion,
            sdn_list_version=None,
            evidence={
                "subject": subject,
                "transfer_seq": transfer_seq,
                "naive_mode": self.naive_mode,
                "malformed": True,
            },
        )

    def _deny(
        self, failing_assertion: str, screen: ScreenResult | None, evidence: dict
    ) -> GateDecision:
        return GateDecision(
            decision="DENY",
            rule_cite=OFAC_CITE,
            failing_assertion=failing_assertion,
            sdn_list_version=screen.sdn_list_version if screen else None,
            evidence=evidence,
        )
