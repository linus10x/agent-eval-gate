"""The stdio loop driven with StringIO: NDJSON framing, parse-error recovery, EOF.

No real stdio; serve() reads/writes the passed text streams.
"""

import io
import json

from agent_eval_gate.server import ServerState, serve


def _state():
    return ServerState(vendor_ok=True)


def _run(lines):
    stdin = io.StringIO("".join(line + "\n" for line in lines))
    stdout = io.StringIO()
    rc = serve(stdin, stdout, _state())
    out = stdout.getvalue()
    parsed = [json.loads(l) for l in out.splitlines() if l.strip()]
    return rc, out, parsed


def test_serve_handles_ndjson_session():
    # L1: initialize + tools/list each produce exactly one line; the notification none.
    rc, out, parsed = _run([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ])
    assert rc == 0
    assert len(parsed) == 2
    ids = [m["id"] for m in parsed]
    assert ids == [1, 2]
    assert "result" in parsed[0] and "result" in parsed[1]


def test_serve_parse_error_returns_minus32700():
    # L2
    rc, out, parsed = _run(["{not valid json"])
    assert len(parsed) == 1
    assert parsed[0]["error"]["code"] == -32700
    assert parsed[0]["id"] is None


def test_serve_writes_one_message_per_line():
    # L3: every response is a single \n-terminated, independently parseable line.
    rc, out, parsed = _run([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/list"}),
    ])
    physical = [l for l in out.splitlines() if l.strip()]
    assert len(physical) == 2
    for line in physical:
        json.loads(line)  # each parses on its own; no concatenated frames


def test_serve_loop_recovers_after_parse_error():
    # L4: a bad line then a valid initialize -> -32700 then a real result.
    rc, out, parsed = _run([
        "}}garbage",
        json.dumps({"jsonrpc": "2.0", "id": 9, "method": "initialize"}),
    ])
    assert rc == 0
    assert len(parsed) == 2
    assert parsed[0]["error"]["code"] == -32700
    assert parsed[1]["id"] == 9
    assert "result" in parsed[1]


def test_serve_loop_recovers_after_non_dict_params():
    # L6: a non-dict-params message then a valid initialize -> the loop emits the
    # error for the bad message then answers the initialize. One poison message
    # must never wedge the server or drop later messages. Defense layer 2.
    rc, out, parsed = _run([
        json.dumps({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": "x"}),
        json.dumps({"jsonrpc": "2.0", "id": 2, "method": "initialize"}),
    ])
    assert rc == 0
    assert len(parsed) == 2
    assert "error" in parsed[0]
    assert parsed[0]["id"] == 1
    assert parsed[1]["id"] == 2
    assert "result" in parsed[1]


def test_serve_exits_clean_on_eof():
    # L5: EOF -> clean shutdown, return 0, no traceback.
    stdin = io.StringIO("")
    stdout = io.StringIO()
    assert serve(stdin, stdout, _state()) == 0
