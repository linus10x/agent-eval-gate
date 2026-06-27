"""Pure JSON-RPC/MCP dispatcher: handshake, tool schema, the CENTERPIECE race
polarity, the DENY-vs-error boundary, the fail-closed states, and injection.

handle_request is a PURE function (no stdio); responses are plain dicts.
"""

import builtins
import socket

import pytest

from agent_funds_gate import OFAC_CITE

from agent_eval_gate import server
from agent_eval_gate.server import (
    SERVER_NAME,
    SERVER_VERSION,
    ServerState,
    TOOL_NAME,
    handle_request,
)
from agent_eval_gate.verdict import EvalVerdict

_SDN_VERSION = "2026-06-17"
_SUBJECT = "BLOCKED PERSON ALPHA"


def _state(**kw):
    kw.setdefault("vendor_ok", True)
    return ServerState(**kw)


def _race_args(completed_seq=15, **over):
    args = {
        "subject": _SUBJECT,
        "transfer_seq": 10,
        "required_sdn_version": _SDN_VERSION,
        "screen": {
            "status": "clear",
            "sdn_list_version": _SDN_VERSION,
            "completed_seq": completed_seq,
            "subject": _SUBJECT,
        },
    }
    args.update(over)
    return args


def _call(args, *, rid=1, name=TOOL_NAME):
    return {"jsonrpc": "2.0", "id": rid, "method": "tools/call",
            "params": {"name": name, "arguments": args}}


class _FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def advance(self, dt):
        self.t += dt


def test_initialize_returns_protocol_and_capabilities():
    # S1
    req = {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    resp = handle_request(req, _state())
    result = resp["result"]
    assert isinstance(result["protocolVersion"], str) and result["protocolVersion"]
    assert isinstance(result["capabilities"]["tools"], dict)
    assert result["serverInfo"]["name"] == SERVER_NAME
    assert result["serverInfo"]["version"] == SERVER_VERSION


def test_initialized_notification_returns_none():
    # S2: a notification (no id) yields no response.
    req = {"jsonrpc": "2.0", "method": "notifications/initialized"}
    assert handle_request(req, _state()) is None


def test_tools_list_returns_one_tool_with_schema():
    # S3
    req = {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}}
    resp = handle_request(req, _state())
    tools = resp["result"]["tools"]
    assert len(tools) == 1
    tool = tools[0]
    assert tool["name"] == TOOL_NAME
    schema = tool["inputSchema"]
    required = schema["required"]
    assert "subject" in required
    assert "transfer_seq" in required
    assert "required_sdn_version" in required
    assert "screen" in schema["properties"]
    assert "deadline_s" in schema["properties"]


def test_centerpiece_race_denies_through_tool_call():
    # S4 [POLARITY -- CENTERPIECE]: the OFAC race must DENY THROUGH the tools/call
    # path, naming the real OFAC cite and the ordering assertion, as a SUCCESSFUL
    # (isError false) result. Deliberate break it catches: evaluate.py building the
    # gate with naive_mode=True returns ALLOW here -> this test goes RED.
    resp = handle_request(_call(_race_args()), _state())
    assert "error" not in resp
    result = resp["result"]
    sc = result["structuredContent"]
    assert sc["decision"] == "DENY"
    assert sc["rule_cite"] == OFAC_CITE
    assert sc["failing_assertion"] == "screen_completion_precedes_execution"
    assert result["isError"] is False
    assert isinstance(result["content"][0]["text"], str) and result["content"][0]["text"]


def test_safe_call_allows_through_tool_call():
    # S5: PRESENCE of ALLOW through the tool path.
    resp = handle_request(_call(_race_args(completed_seq=5)), _state())
    result = resp["result"]
    assert result["structuredContent"]["decision"] == "ALLOW"
    assert result["isError"] is False


def test_tool_deny_is_not_jsonrpc_error():
    # S6: a DENY is a result, not an error object; isError false.
    resp = handle_request(_call(_race_args()), _state())
    assert "error" not in resp
    assert "result" in resp
    assert resp["result"]["isError"] is False
    assert resp["result"]["structuredContent"]["decision"] == "DENY"


def test_unknown_method_returns_minus32601():
    # S7
    req = {"jsonrpc": "2.0", "id": 3, "method": "foo/bar", "params": {}}
    resp = handle_request(req, _state())
    assert resp["error"]["code"] == -32601


def test_invalid_request_envelope_returns_minus32600():
    # S8: missing method, and a wrong jsonrpc version.
    no_method = {"jsonrpc": "2.0", "id": 4, "params": {}}
    assert handle_request(no_method, _state())["error"]["code"] == -32600
    bad_version = {"jsonrpc": "1.0", "id": 5, "method": "initialize"}
    assert handle_request(bad_version, _state())["error"]["code"] == -32600


def test_missing_required_argument_returns_minus32602():
    # S9: a missing required arg is a protocol fault, NOT a DENY.
    args = _race_args()
    del args["transfer_seq"]
    resp = handle_request(_call(args), _state())
    assert resp["error"]["code"] == -32602


def test_wrong_typed_argument_returns_minus32602():
    # S10: string seq, JSON bool seq, and an unknown status enum each -> -32602.
    string_seq = _race_args()
    string_seq["transfer_seq"] = "10"
    assert handle_request(_call(string_seq), _state())["error"]["code"] == -32602

    bool_seq = _race_args()
    bool_seq["transfer_seq"] = True
    assert handle_request(_call(bool_seq), _state())["error"]["code"] == -32602

    bad_enum = _race_args()
    bad_enum["screen"]["status"] = "maybe"
    assert handle_request(_call(bad_enum), _state())["error"]["code"] == -32602


def test_missing_screen_argument_denies_not_errors():
    # S11: required fields present but screen omitted -> a safe DENY, isError false.
    args = {"subject": _SUBJECT, "transfer_seq": 10, "required_sdn_version": _SDN_VERSION}
    resp = handle_request(_call(args), _state())
    assert "error" not in resp
    assert resp["result"]["structuredContent"]["decision"] == "DENY"
    assert resp["result"]["structuredContent"]["failing_assertion"] == "screen_present"
    assert resp["result"]["isError"] is False


def test_unknown_tool_name_returns_minus32602():
    # S12
    resp = handle_request(_call(_race_args(), name="delete_everything"), _state())
    assert resp["error"]["code"] == -32602


def test_tool_call_uses_clock_and_evaluator_seam():
    # S13: a fake clock + a slow fake evaluator (advances past 90) wired through
    # ServerState -> the tools/call result DENYs on the deadline.
    clock = _FakeClock()

    def slow_eval(request):
        clock.advance(120.0)
        return EvalVerdict("ALLOW", None, None, _SDN_VERSION, {})

    resp = handle_request(_call(_race_args(completed_seq=5)), _state(clock=clock, evaluator=slow_eval))
    sc = resp["result"]["structuredContent"]
    assert sc["decision"] == "DENY"
    assert sc["failing_assertion"] == "evaluation_deadline_exceeded"


def test_vendor_drift_state_denies_every_tool_call():
    # S14 [STATIC-GUARD/fail-closed]: a drifted vendor state DENYs, never ALLOWs.
    resp = handle_request(_call(_race_args(completed_seq=5)), _state(vendor_ok=False))
    sc = resp["result"]["structuredContent"]
    assert sc["decision"] == "DENY"
    assert sc["failing_assertion"] == "vendor_integrity_failure"
    assert resp["result"]["isError"] is False


def test_response_envelope_shape():
    # S15
    ok = handle_request({"jsonrpc": "2.0", "id": 7, "method": "initialize"}, _state())
    assert ok["jsonrpc"] == "2.0"
    assert ok["id"] == 7
    err = handle_request({"jsonrpc": "2.0", "id": 8, "method": "no/such"}, _state())
    assert err["jsonrpc"] == "2.0"
    assert err["id"] == 8
    assert isinstance(err["error"]["code"], int)
    assert isinstance(err["error"]["message"], str) and err["error"]["message"]


def test_non_object_params_returns_error():
    # S17: a spec-legal JSON-RPC message whose params is an array, a string, or a
    # number is not a dict. handle_request must return a JSON-RPC error object
    # (-32602), NOT raise, NOT a tools/call DENY-shaped success. Defense layer 1.
    for method in ("tools/call", "initialize"):
        for bad in ([1, 2], "x", 5):
            req = {"jsonrpc": "2.0", "id": 1, "method": method, "params": bad}
            resp = handle_request(req, _state())
            assert "error" in resp, f"{method} params={bad!r} must be a JSON-RPC error"
            assert "result" not in resp, f"{method} params={bad!r} must not be a success"
            assert resp["error"]["code"] == -32602


def test_arguments_are_data_not_instructions(monkeypatch):
    # S16 [INJECTION]: code-like argument payloads flow to the gate as plain
    # strings and decide purely on the ordering invariant; no file write and no
    # socket is tripped during the call.
    def _no_write_open(*a, **k):
        mode = (a[1] if len(a) > 1 else k.get("mode", "r"))
        if any(c in mode for c in ("w", "a", "x", "+")):
            raise AssertionError("the tool call attempted a file WRITE")
        return _real_open(*a, **k)

    _real_open = builtins.open
    monkeypatch.setattr(builtins, "open", _no_write_open)

    def _no_socket(*a, **k):
        raise AssertionError("the tool call attempted a network socket")

    monkeypatch.setattr(socket, "socket", _no_socket)

    payload = "__import__('os').system('rm -rf /')"
    args = _race_args()
    args["subject"] = payload
    args["screen"]["subject"] = payload  # keep bound so only ordering decides
    args["required_sdn_version"] = payload
    args["screen"]["sdn_list_version"] = payload
    resp = handle_request(_call(args), _state())
    sc = resp["result"]["structuredContent"]
    # The race (completed_seq 15 > transfer_seq 10) still DENYs on ORDERING; the
    # payload was inert data, never executed and never path-selecting.
    assert sc["decision"] == "DENY"
    assert sc["failing_assertion"] == "screen_completion_precedes_execution"
    assert sc["evidence"]["subject"] == payload
