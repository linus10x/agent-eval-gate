"""Vendored-gate pinning: content digests, provenance, real-surface reuse,
anti-clone, anti-defeat statics, and the startup refusal on drift."""

import hashlib
import re
import shutil
from pathlib import Path

from agent_eval_gate import server
from agent_eval_gate.vendor_integrity import check_vendor_integrity

REPO_ROOT = Path(__file__).resolve().parent.parent
VENDOR_DIR = REPO_ROOT / "vendor" / "agent_funds_gate"
VENDOR_MD = REPO_ROOT / "vendor" / "VENDOR.md"
SRC_DIR = REPO_ROOT / "src" / "agent_eval_gate"
PINNED_COMMIT = "1441a7c00ecb333f525a56d9ac9b54d6416e2b6a"
VENDORED_FILES = ("__init__.py", "decision.py", "gate.py", "screening.py")


def _recorded_digests():
    text = VENDOR_MD.read_text()
    digests = {}
    for name in VENDORED_FILES:
        m = re.search(rf"`agent_funds_gate/{re.escape(name)}`\s*\|\s*`([0-9a-f]{{64}})`", text)
        assert m, f"no recorded digest for {name} in VENDOR.md"
        digests[name] = m.group(1)
    return digests


def test_vendored_gate_matches_pinned_digests():
    # V1 [POLARITY -- vendor drift]: recompute each SHA-256 and match VENDOR.md.
    # Deliberate break it catches: edit any vendored file -> RED.
    recorded = _recorded_digests()
    for name in VENDORED_FILES:
        actual = hashlib.sha256((VENDOR_DIR / name).read_bytes()).hexdigest()
        assert actual == recorded[name], f"vendored {name} drifted from pinned digest"


def test_vendor_md_records_upstream_and_commit():
    # V2 provenance
    text = VENDOR_MD.read_text()
    assert "agent-funds-gate" in text
    assert PINNED_COMMIT in text
    assert "MIT" in text
    assert "reused upstream IP" in text


def test_server_imports_real_gate_surface():
    # V3 reuse, not re-implementation
    from agent_funds_gate import (
        FundsGate,
        GateDecision,
        OFAC_CITE,
        ScreenResult,
        ScreenStatus,
    )

    assert isinstance(OFAC_CITE, str) and OFAC_CITE
    screen = ScreenResult(ScreenStatus.CLEAR, "2026-06-17", completed_seq=15, subject="X")
    decision = FundsGate("2026-06-17").authorize(subject="X", transfer_seq=10, screen=screen)
    assert isinstance(decision, GateDecision)


def test_src_defines_no_gate_logic():
    # V4 [STATIC-GUARD anti-clone]
    for py in SRC_DIR.rglob("*.py"):
        text = py.read_text()
        assert not re.search(r"class\s+FundsGate\b", text), f"{py} defines FundsGate"
        assert not re.search(r"def\s+authorize\b", text), f"{py} defines authorize"
        assert not re.search(r"completed_seq\s*(>=|<=|>|<|==|!=)", text), (
            f"{py} compares completed_seq -- ordering logic must live only in the gate"
        )
        assert not re.search(r"(>=|<=|>|<|==|!=)\s*completed_seq", text), (
            f"{py} compares completed_seq -- ordering logic must live only in the gate"
        )

    evaluate_text = (SRC_DIR / "evaluate.py").read_text()
    assert re.search(r"from\s+agent_funds_gate\s+import\b.*FundsGate", evaluate_text), (
        "evaluate.py must import FundsGate from agent_funds_gate"
    )


def test_no_naive_mode_in_src():
    # V5 [STATIC-GUARD anti-defeat]
    for py in SRC_DIR.rglob("*.py"):
        text = py.read_text()
        assert not re.search(r"naive_mode\s*=\s*True", text), f"{py} invokes the documented defeat"


def test_no_allow_literal_in_src():
    # V6 [STATIC-GUARD fail-closed]: the only ALLOW reaching output is read out of
    # a real GateDecision, never hand-written.
    for py in SRC_DIR.rglob("*.py"):
        text = py.read_text()
        assert not re.search(r"""['"]ALLOW['"]""", text), f"{py} hand-writes an ALLOW literal"


def test_startup_integrity_refuses_to_serve_on_drift(tmp_path, monkeypatch):
    # V7: a drifted tmp vendor -> check_vendor_integrity False; main() refuses to
    # serve and returns EXIT_VENDOR_DRIFT. (Presence of the safe path -- the real,
    # unmodified vendor passing -- is asserted by V1 and below.)
    tmp_vendor = tmp_path / "vendor"
    shutil.copytree(REPO_ROOT / "vendor", tmp_vendor)
    gate_file = tmp_vendor / "agent_funds_gate" / "gate.py"
    gate_file.write_bytes(gate_file.read_bytes() + b"\n# drift\n")
    assert check_vendor_integrity(
        vendor_dir=tmp_vendor / "agent_funds_gate",
        vendor_md=tmp_vendor / "VENDOR.md",
    ) is False
    # And the clean vendor passes (the gate did not become deny-everything).
    assert check_vendor_integrity() is True

    # main() reads the integrity check and refuses to serve before touching stdin.
    monkeypatch.setattr(server, "check_vendor_integrity", lambda: False)
    assert server.main([]) == server.EXIT_VENDOR_DRIFT
