"""Pinned-vendor integrity: recompute the four SHA-256 digests vs VENDOR.md.

A drifted vendored control invalidates the proof, so the server checks this at
startup (refuse to serve) and on every tool call (DENY). Any missing file,
unreadable VENDOR.md, missing digest row, or mismatch returns False (fail
closed). No exception escapes.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parent.parent.parent
_DEFAULT_VENDOR_DIR = _REPO_ROOT / "vendor" / "agent_funds_gate"
_DEFAULT_VENDOR_MD = _REPO_ROOT / "vendor" / "VENDOR.md"
_VENDORED_FILES = ("__init__.py", "decision.py", "gate.py", "screening.py")


def check_vendor_integrity(
    vendor_dir: Path | None = None,
    vendor_md: Path | None = None,
) -> bool:
    vendor_dir = _DEFAULT_VENDOR_DIR if vendor_dir is None else vendor_dir
    vendor_md = _DEFAULT_VENDOR_MD if vendor_md is None else vendor_md
    try:
        text = vendor_md.read_text()
    except OSError:
        return False
    for name in _VENDORED_FILES:
        m = re.search(
            rf"`agent_funds_gate/{re.escape(name)}`\s*\|\s*`([0-9a-f]{{64}})`", text
        )
        if not m:
            return False
        try:
            actual = hashlib.sha256((vendor_dir / name).read_bytes()).hexdigest()
        except OSError:
            return False
        if actual != m.group(1):
            return False
    return True
