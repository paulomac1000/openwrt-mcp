---
description: Read-only MCP server for OpenWRT router management and diagnostics
doc_id: ref.openwrt-mcp
type: ref
status: active
rigor_tier: L0
ttl_days: 180
stability: stable
ai_scope: review_only
domain: mcp
tags: ["openwrt", "mcp", "router", "ssh", "read-only"]
upstream: []
source_of_truth: true
last_verified: 2026-05-11
owners: ["backend-team"]
---

# OpenWRT-MCP

Read-only MCP (Model Context Protocol) server for OpenWRT router
management and diagnostics. Enables AI assistants to observe and analyze
an OpenWRT router without any write access.

## Requirements

- Python 3.13+
- OpenWRT router with SSH access
- Docker (optional, for containerized deployment)

## Quick Start

```bash
cp .env.example .env
# Edit .env: set OPENWRT_HOST, OPENWRT_SSH_KEY
# For Docker: uncomment MCP_UNSAFE_PUBLIC_ACCESS_CONFIRMED=1
docker compose up -d
curl http://localhost:9094/health
```

## Quick Test (without Docker)

```bash
pip install -e ".[dev]"
pytest tests/unit/ tests/integration/ -q       # 137 tests
pytest tests/unit/ --cov=openwrt_mcp -q         # 80%+ coverage
ruff check . && ruff format --check .           # 0 errors
mypy src/openwrt_mcp/ --strict                  # 0 errors
bandit -r src/openwrt_mcp/ -ll                  # 0 issues
```

## Documentation

- [Full Reference](docs/ref.openwrt-mcp.md) — architecture, tools,
  security, testing
- [Glossary](docs/meta/glossary.md) — terminology definitions
- [Document Registry](docs/meta/doc-registry.md) — index of all documents
- [CHANGELOG](CHANGELOG.md) — version history

## License

MIT
