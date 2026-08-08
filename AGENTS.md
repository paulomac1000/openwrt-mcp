---
description: Repository-wide operating contract for agents changing the OpenWRT MCP server.
doc_id: guide.agent-contribution
type: guide
status: active
rigor: operational
owners:
  - openwrt-mcp-maintainers
verification: Run .venv/bin/python scripts/ci.py from the repository root.
---
# Repository instructions for agents

## Scope and precedence

This file governs the repository. Direct user instructions and platform safety rules have higher authority. The immutable standards reference in `standards-lock.yaml` governs architecture, documentation, agent instructions, and CI/CD.

## Supported profile

The production profile is **L1, POSIX local-process, read-only MCP over stdio** plus a loopback health endpoint. CPython 3.12.x is the supported interpreter line. Do not claim L2 compliance until authenticated principal context, authorization policy, and stable target-binding/revalidation are implemented. Do not add REST, legacy HTTP+SSE, or another invocation transport to this profile. Public write tools remain inactive until principal-bound authorization and expiring approval exist.

## Architecture boundaries

- `settings.py` owns immutable, fail-fast process configuration.
- `application.py` owns capability manifests, closed input schemas, deadlines, response limits, and target-wide serialization.
- `registration.py` is the official MCP SDK adapter and must publish the exact kernel-owned input schema.
- `mcp_compat.py` is the only allowed boundary around version-pinned private MCP 2.0.0 registration internals; it must fail closed on SDK/schema drift.
- `ssh_client.py` owns one event-loop-bound SSH connection. Cancellation, timeout, or connection loss invalidates that session before reconnect; no command is replayed automatically.
- `server.py` owns MCP stdio, the independent health listener, and readiness probes which use separate explorer instances.

## Safety boundaries

Never interpolate unvalidated input into shell commands. Do not expose credentials, raw protected upstream errors, router secrets, MAC addresses, DHCP data, IP topology, or authentication material through logs or uncontrolled exceptions. Audit files must not follow a symlink target and are created mode 0600. Writes are not retried after ambiguous transport failure. Reads are also not automatically replayed after connection loss; retry semantics require operation-specific evidence and policy.

## Commands

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python scripts/ci.py
```

In a restricted environment, install the project without dependencies, run every deterministic test possible, and report every unavailable provider- or laboratory-backed check. Never substitute a fake SDK for official protocol evidence.

## Test integrity

Do not weaken assertions, lower coverage, hide failures, or mark executable behavior as TODO. The deterministic branch-coverage gate is at least 90%. Official-client tests must skip when the test-only SDK fake is active and must run in hosted CI with exact `mcp==2.0.0`.

Environment-dependent real-router behavior belongs in `tests/integration/test_real_router_acceptance.py` under the `lab` marker. Those tests must be executable and may skip only when `OPENWRT_LAB_RUN=1` or required laboratory input is absent. `docs/production-acceptance.md` defines the required environment and evidence. The only accepted `NOT_IMPLEMENTED` placeholder is the future write authorization/approval workflow in `tests/integration/test_real_router_todos.py`, because write capabilities are inactive in this profile.

## Completion criteria

Code, manifests, schemas, documentation, workflows, committed lockfiles, wheel, and container must agree. The exact final SHA must pass provider-backed CI before the PR is ready. A claim of “production verified against real OpenWRT” additionally requires the real-router lab suite to report **5 passed, 0 failed, 0 skipped** for the intended router/firmware environment. Without that record, describe the tree as a production-ready candidate awaiting environment acceptance, not as real-router verified.
