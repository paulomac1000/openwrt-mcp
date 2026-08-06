# OpenWRT MCP

Hardened read-only MCP server for bounded OpenWRT diagnostics.

## Current profile

- Official MCP Python SDK v2 over stdio.
- 24 stable names in the supported catalog.
- 19 active read-only tools exposed through `tools/list`.
- Five write or destructive capabilities retained as inactive metadata and not registered.
- One invocation kernel shared by MCP, optional REST, and tests.
- Target-wide serialization for operations marked `concurrent_safe=false`.

## Requirements

- Python 3.12–3.14.
- An OpenWRT router reachable over SSH.
- An SSH key or password.
- An enrolled `known_hosts` file in real mode.

Copy `.env.example` and set at least:

```env
OPENWRT_HOST=192.168.1.1
OPENWRT_USER=root
OPENWRT_SSH_KEY=/absolute/path/to/openwrt_id_ed25519
OPENWRT_KNOWN_HOSTS=/absolute/path/to/known_hosts
MCP_TRANSPORT=stdio
```

Generate the host identity file before first use:

```bash
ssh-keyscan -H 192.168.1.1 > known_hosts
```

`OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK=1` is an explicit non-production exception. It emits a warning and is never accepted for dormant write execution.

## Local development

```bash
python -m venv .venv
. .venv/bin/activate
python -m pip install -e ".[dev]"
OPENWRT_MOCK_MODE=1 python scripts/mock_smoke.py
python -m pytest
```

Start the MCP server:

```bash
openwrt-mcp
```

The hardened MCP transport is stdio. Legacy HTTP plus SSE has been removed.

## Optional REST adapter

REST is disabled by default, binds only to `127.0.0.1`, and uses the same invocation kernel as MCP. A bearer token is mandatory whenever REST is enabled:

```env
ENABLE_REST_API=true
MCP_REST_AUTH_TOKEN=replace-with-a-long-random-token
```

Requests without a valid `Authorization: Bearer ...` header are rejected. Request bodies have a configured byte limit, invalid JSON is rejected, and wildcard origins are not accepted.

## Deadlines and concurrency

Public MCP tools do not accept a timeout override. Each capability manifest owns its deadline. The internal SSH command timeout is capped by that deadline. Non-concurrent-safe operations are serialized for the whole configured router target unless an explicit reviewed concurrency group is declared.

## Response compatibility

The active tools preserve historical read DTOs, including connectivity summaries, router-context aggregate fields, `reachable` on ping, `resolved` on DNS lookup, parsed Wi-Fi scan networks, and stable DHCP event values.

Controlled tool failures return sanitized `CallToolResult` content with `is_error=true`. Unexpected SDK or protocol failures remain protocol-level errors.

## CI and standards evidence

`standards-lock.yaml` pins `paulomac1000/ai-skills` to revision `661ff01a5e70d58d6c94a12545b24647e52063ed`.

Hosted CI:

1. checks out the exact candidate SHA;
2. checks out the trusted `ai-skills` revision outside the candidate tree;
3. runs the trusted AFDS and workflow-policy validators;
4. generates hashed runtime and development locks;
5. runs Ruff, formatting, mypy strict, Bandit, pip-audit, tests, and branch coverage;
6. builds and smokes the exact wheel through the official MCP client;
7. builds and smokes a container from the tested wheel and runtime lock.

The generated transitive lock files are retained as CI evidence. Committing reviewed generated locks remains follow-up work for cross-run reproducibility.

## Documentation

- `AGENTS.md` — repository operating instructions.
- `docs/openwrt-mcp.md` — architecture and operational contract.
- `docs/migration-assessment.yaml` — evidence, residual risks, and real-system TODOs.
- `standards-lock.yaml` — immutable standards source.

## Safety boundary

The project is currently read-only. Do not activate write tools until authenticated authorization, principal-bound expiring approval, verification, compensation, and isolated-router tests are implemented and reviewed.
