from __future__ import annotations

import enum
from dataclasses import dataclass
from typing import Protocol


class ScreenStatus(enum.Enum):
    CLEAR = "clear"
    HIT = "hit"
    PENDING = "pending"
    ERROR = "error"


@dataclass(frozen=True)
class ScreenResult:
    """The outcome of an OFAC SDN screen for one subject.

    ``completed_seq`` is the value of a monotonic counter at the moment the
    screen reached a terminal state. It is ``None`` while the screen is still
    PENDING. The gate compares it against the transfer's own sequence number to
    decide whether the screen *completed before* the value moved.
    """

    status: ScreenStatus
    sdn_list_version: str
    completed_seq: int | None
    subject: str


class ScreeningProvider(Protocol):
    def screen(self, subject: str, sdn_list_version: str) -> ScreenResult: ...
