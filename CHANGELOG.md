# Changelog

## [1.2.0] — 2026-05-12

### Added
- `get_router_context` — unified router context snapshot (system, wifi, DHCP, connectivity)
- `describe_router_capabilities` — server introspection with tool manifests
- `uci_set`, `uci_commit` — UCI write/commit tools (requires `ENABLE_WRITE_OPERATIONS=1`)
- `reboot_device` — router reboot (requires `ENABLE_WRITE_OPERATIONS=1`)
- `restart_interface` — restart network interface (requires `ENABLE_WRITE_OPERATIONS=1`)
- `reload_network` — reload network services (requires `ENABLE_WRITE_OPERATIONS=1`)
- `ping_host`, `traceroute_host`, `nslookup_host` — standalone network diagnostic tools
- `wifi_scan` — neighboring WiFi network survey
- `ENABLE_WRITE_OPERATIONS` environment variable (default: false)
- `SSHConnection.execute_write()` — separate write command validation path
- Write command validation in `SecurityValidator` (interface name, loopback protection)
- `_inject_risk_prefixes()` — dynamic risk prefix injection from manifest SSOT
- `UbusClient` — ubus JSON-RPC transport module
- `cat /proc/loadavg` added to allowed read-only patterns
- JSON Schema documentation (`schema/`)
- `RISKS_AND_CAVEATS` section in documentation (write tool risks, mock strategy)

### Changed
- Registered tools: `13` → `24`
- Writer module (`writer.py`) now uses `execute_write()` for all write operations
- Integration tests now skip when `OPENWRT_HOST` is not set
- `MCPWrapper` uses shared event loop for persistent SSH connections
- `.env` loaded from `conftest.py` for consistent env var injection
- Integration tests with real OpenWRT router added (19 READ tools)
- Mock integration tests for dangerous write tools added (10 tests)
- `timeout_seconds: int | None = None` → `int = SSH_TIMEOUT` for all I/O tools (fixes MCP SSE transport)
- `request_id` (UUID) included in SSH connection log lines for traceability
- `ci.yml`: integration tests accept exit code 5 (skip when OPENWRT_HOST not set)
- `ci.yml`: docker smoke tool count check `13` → `24`
- Docker base image: `python:3.13-slim` → `python:3.14-slim`
- fastmcp: `>=2.0.0,<3.0.0` → `>=3.2.4,<4.0.0`
- `server.py`: `get_all_tools()` supports FastMCP 3.x (lazy cache via `list_tools`)

### Removed
- Device registry (`db/` package and related tools) — out of scope

### Metrics
- Coverage: 86%
- 279 tests (200 unit + 53 integration + 8 smoke + 18 e2e)
- 0 errors: ruff / mypy --strict / bandit -ll

## [1.1.0] — 2026-05-11

### Changed
- Repository structure refactored: `openwrt_explorer.py` split into 4 modules under `tools/`
  (`ssh_client.py`, `explorer.py`, `registration.py`, `response_helpers.py`)
- `constants.py` moved to `tools/constants.py` as SSOT
- Python base image: `python:3.11-slim` → `python:3.13-slim`
- `requires-python` upgraded from `>=3.11` to `>=3.13`
- `ruff target-version`: `py311` → `py313`
- `mypy python_version`: `3.11` → `3.13`

### Added
- `timeout_seconds: int | None = None` parameter to all 13 I/O tools
- `@since v1.0.0` annotations in all tool docstrings
- `MCPWrapper` (Canonical Template 8 from mcp_standards.md) for integration tests
- Per-tool integration tests: 7 no-arg + 7 param + 3 invalid args
- `SSHConnection.cancel()` — cancellation signal for long-running operations
- `_meta` envelope (`request_id`, `duration_ms`, `tool_version`) on all 13 tools
- `server.py` unit tests with 60%+ coverage (no longer excluded from coverage)

### Fixed
- `SSHConnection.execute()`: timeout reset moved to `finally` block
- `_error_dict_extended` no longer wrapped as `success: true` by tool wrappers
- Duplicate MAC validation in `get_device_dhcp_details()` removed
- Dead `hours_back` parameter removed from `search_dhcp_logs()`
- `concurrent_safe` changed from `true` to `false` in manifests (TOCTOU race)
- `HEALTH_STATE` now protected by `threading.Lock`
- `mypy` and `bandit` in CI no longer suppressed with `|| true` — errors block pipeline
- Latency manifest for `test_router_connection`: `"fast"` → `"moderate"`
- `tool_version` in `observability.py`: hardcoded → `TOOLS_VERSION` constant
- Hardcoded fallback gateway `192.168.0.1` in `diagnose_router_connectivity` removed
- `MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1` added to Docker deployment (port forwarding)

### Dependencies
- Bump `asyncssh`: `>=2.13.0,<3.0.0` → `>=2.23.0,<3.0.0`
- Bump `starlette`: `>=0.27.0` → `>=1.0.0`
- Bump `uvicorn`: `>=0.22.0` → `>=0.46.0`
- Bump `pytest`: `>=7.0.0` → `>=9.0.3`
- Bump `pytest-asyncio`: `>=0.21.0` → `>=1.3.0`
- Bump `pytest-mock`: `>=3.10.0` → `>=3.15.1`
- Bump `docker/build-push-action`: `@v6` → `@v7`
- Bump `docker/metadata-action`: `@v5` → `@v6`
- Bump `docker/login-action`: `@v3` → `@v4`
- Bump `actions/setup-python`: `@v5` → `@v6`
- Bump `docker/setup-buildx-action`: `@v3` → `@v4`

### Metrics
- Coverage: 80.34% (server.py included — 60% coverage)
- 137 tests (115 unit + 22 integration)
- 0 errors: ruff / mypy --strict / bandit -ll
- Docker build: Python 3.13, ~25s

## [1.0.0] — 2026-05-11

### Added
- Initial release with 13 read-only MCP tools for OpenWRT
- SSH command whitelist security validator
- REST API on port 9096
- Health endpoint on port 9094
- MCP SSE transport on port 9095
- Extended L2+ error responses with structured codes
- Tool manifest generation with capability descriptors
- Per-tool observability (request_id, _meta envelope, counters)
- Docker deployment with docker compose
- CI pipeline with ruff, mypy, bandit, coverage enforcement (83%)
- Smoke and E2E test suites
