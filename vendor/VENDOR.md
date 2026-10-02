# Vendored control: agent_funds_gate

This directory holds a verbatim, pinned copy of the runtime source of the
`agent-funds-gate` control. The MCP eval-gate server reuses this control
unchanged and writes zero gate logic of its own. The server is a transport and
fail-closed wrapper around this control; the OFAC ordering decision lives only
here.

## Provenance

- Upstream: the public repository https://github.com/linus10x/agent-funds-gate.
  The four files in this directory are byte-identical to commit
  `1441a7c00ecb333f525a56d9ac9b54d6416e2b6a` on that repository (SHA-256 of
  each file). Public commit `5995fec2fb4de9e5a095fc30dd8f13270c1ae141` changes
  `gate.py` and does not match this copy.
- Recorded pin: `19354ac0d086234eda3ace14383dadf1681431c5`. That identifier was
  stored with this copy. It is not a commit in the public repository history.
- License: MIT. This is reused upstream IP; the server does not re-own or re-license the control.

Only the four runtime source files are vendored. Upstream `tests/`, `demo/`,
`pyproject.toml`, and caches are deliberately not copied: the server ships its
own transport, evaluation wrapper, and tests, and carrying upstream tests would
imply we re-own them and would bloat the single-clone footprint.

## Pinned content digests (SHA-256)

Recorded at copy time. `tests/test_vendor_integrity.py`
recomputes these on every run, and the server checks them before serving, so any
silent drift of the vendored control fails the integrity test and the server
refuses to start. Content is pinned by these digests.

| file | sha256 |
|---|---|
| `agent_funds_gate/__init__.py` | `28e68e69b6a3af1fa953e482b5f60279fec62f02c66d97dae6279ff12290fe99` |
| `agent_funds_gate/decision.py` | `dd2268c06e3c03645c7b2af56207109b250cc67922b787d8557157c8f666481a` |
| `agent_funds_gate/gate.py` | `d0ce394941a2a8607e4fab65f207fe84768fe7350ef6e6c2ffa39beee28b88e7` |
| `agent_funds_gate/screening.py` | `5a8a65b98a31f546104901820d948d5730f274afe70e76efde631dd9a25deaab` |

## How to re-sync

To pull a newer pinned version of the control:

1. Check out the new commit in https://github.com/linus10x/agent-funds-gate.
2. Copy the four runtime files into `vendor/agent_funds_gate/`.
3. Recompute each file digest (`shasum -a 256 <file>`) and update the table above
   plus the recorded pin line.
4. Run the test suite. The integrity test confirms the vendored content matches
   the recorded digests, and the polarity tests confirm the control still holds.
