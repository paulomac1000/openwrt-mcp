---
description: Defines the isolated real-OpenWRT acceptance gate and evidence required before claiming production verification.
doc_id: guide.real-openwrt-production-acceptance
type: guide
status: active
rigor: operational
owners:
  - openwrt-mcp-maintainers
verification: Run the six lab-marked tests with OPENWRT_LAB_RUN=1 and retain the JUnit evidence.
review_triggers:
  - SSH lifecycle changes
  - supported OpenWRT versions change
  - active read-tool behavior changes
  - write capability activation
---
# Production acceptance for real OpenWRT

This runbook is the final environment-dependent gate for the supported **L1 POSIX local-process, read-only, stdio** profile. All deterministic, SDK, dependency, wheel, container, security, and release-artifact checks belong in ordinary CI. The tests here exist only for behavior which cannot be proven without a real SSH server and OpenWRT target.

## Laboratory requirements

Use an isolated router or disposable OpenWRT VM which may safely lose SSH sessions. Do not run the cancellation/timeout tests against a shared production router. The test account may be `root` because the current profile is read-only, but the SSH key and `known_hosts` file must be dedicated to the laboratory.

Set the normal runtime variables plus the laboratory variables:

```bash
export OPENWRT_LAB_RUN=1
export OPENWRT_MOCK_MODE=0
export OPENWRT_HOST=192.0.2.1
export OPENWRT_PORT=22
export OPENWRT_USER=root
export OPENWRT_SSH_KEY="$PWD/keys/openwrt_id_ed25519"
export OPENWRT_KNOWN_HOSTS="$PWD/keys/known_hosts"
export OPENWRT_LAB_SLOW_TARGET=198.51.100.254

# Set these when the router differs from the safe defaults used by the all-tool test.
export OPENWRT_LAB_DEVICE_IP=192.0.2.1
export OPENWRT_LAB_DIAGNOSTIC_HOST=127.0.0.1
export OPENWRT_LAB_DNS_NAME=openwrt.lan
export OPENWRT_LAB_DNS_SERVER=127.0.0.1
export OPENWRT_LAB_WIFI_RADIO=wlan0
export OPENWRT_LAB_SEARCH_TERM=dnsmasq
```

`OPENWRT_LAB_SLOW_TARGET` must be an address the router routes but does not answer quickly. Verify this property manually before the test; the cancellation and timeout cases intentionally start a bounded `ping` against it. Never set `OPENWRT_INSECURE_SKIP_HOST_KEY_CHECK` during acceptance.

`OPENWRT_LAB_DEVICE_IP` is used only as a lookup key and may name a device which has no current lease. `OPENWRT_LAB_DIAGNOSTIC_HOST` must be safe to ping and traceroute from the router. `OPENWRT_LAB_DNS_NAME` and `OPENWRT_LAB_DNS_SERVER` must form a lookup that succeeds on the target. `OPENWRT_LAB_WIFI_RADIO` must identify an interface accepted by `iwinfo <radio> scan`. The purpose of these overrides is to adapt the test to the real router, not to bypass a failing advertised capability.

## Run the gate

Install the exact committed development lock and project, then execute only the lab marker:

```bash
python3.12 -m venv .venv
.venv/bin/python -m pip install --require-hashes -r requirements-dev.lock
.venv/bin/python -m pip install --no-deps --no-build-isolation -e .
.venv/bin/python -m pytest -vv -m lab \
  tests/integration/test_real_router_acceptance.py \
  --junitxml=real-router-acceptance.xml
```

A production-verification record for the current candidate requires **6 passed, 0 failed, 0 skipped** from this file. The tests prove:

1. a deliberately wrong host key prevents creation of a usable command session;
2. the official MCP client can list the 19 closed-schema tools and perform the baseline real-router read smoke;
3. every one of the 19 advertised read tools executes successfully through the official MCP client with lab-safe arguments;
4. task cancellation invalidates the SSH session, permits a fresh connection, and leaves no matching `ping` process in `ps`;
5. an AsyncSSH command timeout has the same cleanup property and returns exit status 124;
6. the invocation kernel enforces the declared response-byte limit on a real OpenWRT response.

The all-tool test is intentionally strict. If `traceroute`, `iwinfo scan`, local DNS, firewall inspection, package listing, or another advertised capability cannot execute in the supported lab profile, treat that as a product/capability issue. Do not turn the test into a skip merely to obtain a green record.

Store the JUnit XML together with the router model, OpenWRT version, kernel version, Python version, `asyncssh` version, `mcp` version, tested git SHA, and UTC timestamp. Do not commit private keys, `known_hosts`, router addresses, MAC addresses, DHCP data, or raw router logs as evidence.

## Deliberately deferred write profile

`tests/integration/test_real_router_todos.py` contains one owned `NOT_IMPLEMENTED` placeholder for a future authenticated write profile. It is **not** a missing requirement for the current L1 read-only profile. Do not implement or enable write tools until principal-bound authorization, expiring approvals, audit semantics, plan/execute/verify behavior, and compensation policy have been reviewed.
