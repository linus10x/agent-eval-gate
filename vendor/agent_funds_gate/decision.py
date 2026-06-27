from __future__ import annotations

from dataclasses import dataclass
from typing import Literal


@dataclass(frozen=True)
class GateDecision:
    """The structured verdict of the gate. Reads like a control, not a print statement.

    On DENY, ``rule_cite`` and ``failing_assertion`` are always populated.
    On ALLOW, both are ``None``.
    """

    decision: Literal["ALLOW", "DENY"]
    rule_cite: str | None
    failing_assertion: str | None
    sdn_list_version: str | None
    evidence: dict
