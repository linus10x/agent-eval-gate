"""MCP / JSON-RPC 2.0 server over stdio (stdlib only).

Exposes ONE tool, ``authorize_funds_transfer``, that runs the request through the
governed, fail-closed evaluation (guard.guarded_evaluate -> evaluate -> the
vendored gate). The dispatcher is a PURE function (handle_request); the stdio
loop (serve) is a thin wrapper over it so the protocol is tested with StringIO.

A tool DENY is a SUCCESSFUL result (isError false). JSON-RPC error objects are
reserved for protocol/argument faults only (parse, envelope, method, params).
"""

from __future__ import annotations

import json
import sys
import time
from dataclasses import dataclass, field
from typing import Callable, TextIO

from .evaluate import evaluate
from .guard import guarded_evaluate
from .vendor_integrity import check_vendor_integrity
from .verdict import EvalRequest, EvalVerdict

SERVER_NAME = "agent-eval-gate"
SERVER_VERSION = "0.1.0"
PROTOCOL_VERSION = "2025-06-18"
TOOL_NAME = "authorize_funds_transfer"

# Process exit codes (the served JSON-RPC error codes are separate; see below).
EXIT_OK = 0
EXIT_VENDOR_DRIFT = 4
EXIT_INTERNAL = 5

# JSON-RPC 2.0 error codes.
_PARSE_ERROR = -32700
_INVALID_REQUEST = -32600
_METHOD_NOT_FOUND = -32601
_INVALID_PARAMS = -32602
_INTERNAL_ERROR = -32603

_SCREEN_STATUS_ENUM = ("clear", "hit", "pending", "error")

TOOL_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["subject", "transfer_seq", "required_sdn_version"],
    "properties": {
        "subject": {"type": "string"},
        "transfer_seq": {"type": "integer"},
        "required_sdn_version": {"type": "string"},
        "screen": {
            "type": ["object", "null"],
            "additionalProperties": False,
            "required": ["status", "sdn_list_version", "completed_seq", "subject"],
            "properties": {
                "status": {"type": "string", "enum": list(_SCREEN_STATUS_ENUM)},
                "sdn_list_version": {"type": "string"},
                "completed_seq": {"type": ["integer", "null"]},
                "subject": {"type": "string"},
            },
        },
        "deadline_s": {"type": "number", "exclusiveMinimum": 0},
    },
}

TOOL_DESCRIPTION = (
    "Authorize a funds transfer only if a version-pinned OFAC SDN screen returned "
    "CLEAR and COMPLETED before the transfer executed. Returns a structured DENY "
    "(with the OFAC rule cite) or ALLOW verdict; every unsafe ordering DENYs."
)


class InvalidParams(Exception):
    """Raised by validate_arguments on any protocol/type fault -> JSON-RPC -32602."""


@dataclass
class ServerState:
    vendor_ok: bool
    clock: Callable[[], float] = time.monotonic
    evaluator: Callable[[EvalRequest], EvalVerdict] = evaluate
    server_info: dict = field(
        default_factory=lambda: {"name": SERVER_NAME, "version": SERVER_VERSION}
    )


def _result(rid, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "result": result}


def _error(rid, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": rid, "error": {"code": code, "message": message}}


def _validate_screen(screen) -> dict | None:
    if screen is None:
        return None
    if not isinstance(screen, dict):
        raise InvalidParams("screen must be an object or null")
    extra = set(screen) - {"status", "sdn_list_version", "completed_seq", "subject"}
    if extra:
        raise InvalidParams(f"unknown screen field(s): {sorted(extra)}")
    status = screen.get("status")
    if status not in _SCREEN_STATUS_ENUM:
        raise InvalidParams("screen.status must be one of clear|hit|pending|error")
    sdn = screen.get("sdn_list_version")
    if not isinstance(sdn, str):
        raise InvalidParams("screen.sdn_list_version is required and must be a string")
    if "completed_seq" not in screen:
        raise InvalidParams("screen.completed_seq is required (integer or null)")
    cseq = screen["completed_seq"]
    if cseq is not None and (not isinstance(cseq, int) or isinstance(cseq, bool)):
        raise InvalidParams("screen.completed_seq must be an integer or null")
    subj = screen.get("subject")
    if not isinstance(subj, str):
        raise InvalidParams("screen.subject is required and must be a string")
    return {
        "status": status,
        "sdn_list_version": sdn,
        "completed_seq": cseq,
        "subject": subj,
    }


def validate_arguments(arguments) -> EvalRequest:
    """Hand-written validation (no jsonschema lib). Raises InvalidParams on any
    protocol/type fault. Returns a typed EvalRequest of plain data only."""
    if not isinstance(arguments, dict):
        raise InvalidParams("arguments must be an object")
    extra = set(arguments) - {
        "subject", "transfer_seq", "required_sdn_version", "screen", "deadline_s"
    }
    if extra:
        raise InvalidParams(f"unknown argument(s): {sorted(extra)}")

    subject = arguments.get("subject")
    if not isinstance(subject, str):
        raise InvalidParams("subject is required and must be a string")

    if "transfer_seq" not in arguments:
        raise InvalidParams("transfer_seq is required")
    transfer_seq = arguments["transfer_seq"]
    if not isinstance(transfer_seq, int) or isinstance(transfer_seq, bool):
        raise InvalidParams("transfer_seq must be an integer")

    required_sdn_version = arguments.get("required_sdn_version")
    if not isinstance(required_sdn_version, str):
        raise InvalidParams("required_sdn_version is required and must be a string")

    screen = _validate_screen(arguments.get("screen"))

    deadline_s = arguments.get("deadline_s")
    if deadline_s is not None:
        if isinstance(deadline_s, bool) or not isinstance(deadline_s, (int, float)):
            raise InvalidParams("deadline_s must be a number")
        if deadline_s <= 0:
            raise InvalidParams("deadline_s must be greater than 0")
        deadline_s = float(deadline_s)

    return EvalRequest(
        subject=subject,
        transfer_seq=transfer_seq,
        required_sdn_version=required_sdn_version,
        screen=screen,
        deadline_s=deadline_s,
    )


def _verdict_to_dict(verdict: EvalVerdict) -> dict:
    return {
        "decision": verdict.decision,
        "rule_cite": verdict.rule_cite,
        "failing_assertion": verdict.failing_assertion,
        "sdn_list_version": verdict.sdn_list_version,
        "evidence": verdict.evidence,
    }


def _human_line(verdict: EvalVerdict) -> str:
    # Reads the decision OUT of the verdict; never hand-writes an ALLOW literal.
    detail = verdict.failing_assertion or "screen completed before the transfer executed"
    return f"{verdict.decision}: {detail}"


def _handle_tool_call(rid, params: dict, state: ServerState) -> dict:
    name = params.get("name")
    if name != TOOL_NAME:
        return _error(rid, _INVALID_PARAMS, f"unknown tool: {name!r}")
    try:
        request = validate_arguments(params.get("arguments", {}))
    except InvalidParams as exc:
        return _error(rid, _INVALID_PARAMS, str(exc))

    if not state.vendor_ok:
        # Fail closed: a drifted vendored control DENYs every call (never passes).
        verdict = EvalVerdict(
            decision="DENY",
            rule_cite=None,
            failing_assertion="vendor_integrity_failure",
            sdn_list_version=None,
            evidence={"wrapper": "server", "reason": "vendor_integrity_failure"},
        )
    else:
        verdict = guarded_evaluate(
            request, evaluator=state.evaluator, clock=state.clock
        )

    return _result(rid, {
        "content": [{"type": "text", "text": _human_line(verdict)}],
        "structuredContent": _verdict_to_dict(verdict),
        "isError": False,
    })


def handle_request(request, state: ServerState) -> dict | None:
    """Pure JSON-RPC dispatcher. Returns a response dict, or None for a
    notification. Never raises out on a tools/call."""
    if not isinstance(request, dict):
        return _error(None, _INVALID_REQUEST, "request must be a JSON object")
    rid = request.get("id")
    if request.get("jsonrpc") != "2.0" or not isinstance(request.get("method"), str):
        return _error(rid, _INVALID_REQUEST, "invalid JSON-RPC request envelope")

    method = request["method"]
    if "id" not in request:
        # Notification (e.g. notifications/initialized): carries no response.
        return None

    # Validate params SHAPE before any handler does .get on it. JSON-RPC 2.0
    # permits params to be Array or Object, but every method on THIS server needs
    # an object; an array/string/number params is a params-shape fault -> -32602
    # (Invalid params), per plan 4.7. No method handler may assume a dict without
    # this guard -- a non-dict params must never raise out of the dispatcher.
    params = request.get("params")
    if params is not None and not isinstance(params, dict):
        return _error(rid, _INVALID_PARAMS, "params must be an object")
    params = params or {}

    if method == "initialize":
        requested_pv = params.get("protocolVersion")
        protocol = requested_pv if isinstance(requested_pv, str) and requested_pv else PROTOCOL_VERSION
        return _result(rid, {
            "protocolVersion": protocol,
            "capabilities": {"tools": {}},
            "serverInfo": dict(state.server_info),
        })
    if method == "tools/list":
        return _result(rid, {
            "tools": [{
                "name": TOOL_NAME,
                "description": TOOL_DESCRIPTION,
                "inputSchema": TOOL_SCHEMA,
            }]
        })
    if method == "tools/call":
        return _handle_tool_call(rid, params, state)
    return _error(rid, _METHOD_NOT_FOUND, f"method not found: {method}")


def serve(stdin: TextIO, stdout: TextIO, state: ServerState) -> int:
    """Thin loop over newline-delimited JSON. Recovers from parse errors and
    exits 0 on a clean EOF. One JSON message per output line."""
    for line in stdin:
        if not line.strip():
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            stdout.write(json.dumps(_error(None, _PARSE_ERROR, "parse error")) + "\n")
            stdout.flush()
            continue
        try:
            resp = handle_request(msg, state)
        except Exception:
            # Belt-and-suspenders: one poison message must never wedge the loop or
            # drop later messages. Emit an internal error and keep serving
            # (mirrors the -32700 parse-error recovery above). Fail closed: an
            # exception here is reported as an error, never as an ALLOW.
            rid = msg.get("id") if isinstance(msg, dict) else None
            resp = _error(rid, _INTERNAL_ERROR, "internal error dispatching request")
        if resp is not None:
            stdout.write(json.dumps(resp) + "\n")
            stdout.flush()
    return EXIT_OK


def main(argv: list[str] | None = None) -> int:
    try:
        state = ServerState(vendor_ok=check_vendor_integrity())
        if not state.vendor_ok:
            print(
                "VENDOR INTEGRITY FAILURE: the vendored gate does not match its "
                "pinned SHA-256 digests in vendor/VENDOR.md. Refusing to serve.",
                file=sys.stderr,
            )
            return EXIT_VENDOR_DRIFT
        return serve(sys.stdin, sys.stdout, state)
    except Exception as exc:  # fail closed: never exit 0 on a crash
        print(f"INTERNAL ERROR: {exc!r}", file=sys.stderr)
        return EXIT_INTERNAL


if __name__ == "__main__":
    raise SystemExit(main())
