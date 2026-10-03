"""Integration / acceptance: zero-install, no-network, clone-to-green, framing law.

These tests spawn serve.sh / demo.sh as real subprocesses. No pip install runs;
the wrappers set PYTHONPATH to the in-tree src + vendor only.
"""

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent
SERVE_SH = REPO_ROOT / "serve.sh"
DEMO_SH = REPO_ROOT / "demo.sh"

_SDN_VERSION = "2026-06-17"
_SUBJECT = "BLOCKED PERSON ALPHA"

if shutil.which("bash") is None:
    pytest.skip("bash unavailable", allow_module_level=True)


def _race_session():
    args = {
        "subject": _SUBJECT,
        "transfer_seq": 10,
        "required_sdn_version": _SDN_VERSION,
        "screen": {"status": "clear", "sdn_list_version": _SDN_VERSION,
                   "completed_seq": 15, "subject": _SUBJECT},
    }
    lines = [
        {"jsonrpc": "2.0", "id": 1, "method": "initialize"},
        {"jsonrpc": "2.0", "method": "notifications/initialized"},
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list"},
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": "authorize_funds_transfer", "arguments": args}},
    ]
    return "".join(json.dumps(m) + "\n" for m in lines)


def _no_network_env(extra_pythonpath, tmp_path):
    """An env whose sitecustomize disables socket creation, proving no-network."""
    site_dir = tmp_path / "sitedir"
    site_dir.mkdir()
    (site_dir / "sitecustomize.py").write_text(
        "import socket\n"
        "def _blocked(*a, **k):\n"
        "    raise OSError('network disabled for the no-network proof')\n"
        "socket.socket = _blocked\n"
    )
    env = dict(os.environ)
    parts = [str(site_dir)]
    if extra_pythonpath:
        parts.append(extra_pythonpath)
    env["PYTHONPATH"] = ":".join(parts)
    return env


def _run_serve(script_path, session, env):
    return subprocess.run(
        ["bash", str(script_path)],
        input=session,
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        cwd=str(script_path.parent),
    )


def _race_decision_from(stdout):
    for line in stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        msg = json.loads(line)
        if msg.get("id") == 3:
            return msg["result"]["structuredContent"]["decision"]
    raise AssertionError("no response for the race call (id 3) in serve.sh output")


def test_serve_sh_runs_a_session_no_install_no_network(tmp_path):
    # D1 (LIVE-E2E): spawn serve.sh, pipe the NDJSON race, sockets disabled, no
    # install -> the race response decision is DENY.
    env = _no_network_env(None, tmp_path)
    proc = _run_serve(SERVE_SH, _race_session(), env)
    assert proc.returncode == 0, proc.stderr
    assert _race_decision_from(proc.stdout) == "DENY"


def test_demo_sh_exit_zero_and_transcript():
    # D2 (ACCEPTANCE): demo.sh exits 0 and its transcript carries the race DENY,
    # the safe ALLOW, and the framing law; never "caught a real incident".
    proc = subprocess.run(
        ["bash", str(DEMO_SH)], capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT),
    )
    assert proc.returncode == 0, proc.stderr
    out = proc.stdout
    assert "agent-eval-gate: the race is denied and the safe case is permitted." in out
    assert "the under-governed agent would ALLOW this; the governed gate DENYs it" in out
    assert "DENY" in out
    assert "ALLOW" in out
    assert "caught a real incident" not in out


def test_demo_no_network(tmp_path):
    # D3: sockets disabled during the demo; still exit 0.
    env = _no_network_env(None, tmp_path)
    proc = subprocess.run(
        ["bash", str(DEMO_SH)], capture_output=True, text=True, timeout=60,
        cwd=str(REPO_ROOT), env=env,
    )
    assert proc.returncode == 0, proc.stderr


def test_clone_to_green_pythonpath_wrapper(tmp_path):
    # D4: the wrappers are PYTHONPATH-setting exec wrappers (not bare python3 -m);
    # a COPIED clone runs green from its own tree.
    for script in (SERVE_SH, DEMO_SH):
        text = script.read_text()
        assert "PYTHONPATH=" in text
        assert "src" in text and "vendor" in text
        assert "exec python3 -m" in text

    clone = tmp_path / "clone"
    shutil.copytree(
        REPO_ROOT, clone,
        ignore=shutil.ignore_patterns("__pycache__", "*.pyc", ".pytest_cache", ".git"),
    )
    env = _no_network_env(None, tmp_path)
    proc = _run_serve(clone / "serve.sh", _race_session(), env)
    assert proc.returncode == 0, proc.stderr
    assert _race_decision_from(proc.stdout) == "DENY"
