"""agent-eval-gate: an MCP stdio server wrapping the vendored OFAC funds-transfer
control with two server-level fail-closed promises (a <=90s deadline and
error -> DENY). The gate logic is REUSED from the vendored agent_funds_gate; this
package writes none of its own.

The server-backed names (ServerState, handle_request, serve) are exposed lazily
so that ``python3 -m agent_eval_gate.server`` does not import server.py twice
(once via this package init, once as __main__), which would emit a runpy warning.
The lightweight types and the gate-free helpers import eagerly.
"""

from .evaluate import evaluate
from .guard import guarded_evaluate
from .vendor_integrity import check_vendor_integrity
from .verdict import EvalRequest, EvalVerdict

__all__ = [
    "EvalRequest",
    "EvalVerdict",
    "evaluate",
    "guarded_evaluate",
    "check_vendor_integrity",
    "ServerState",
    "handle_request",
    "serve",
]

_SERVER_NAMES = {"ServerState", "handle_request", "serve"}


def __getattr__(name):
    # PEP 562: defer importing server.py until one of its names is actually used.
    if name in _SERVER_NAMES:
        from . import server

        return getattr(server, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
