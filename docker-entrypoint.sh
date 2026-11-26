#!/bin/sh
set -eu

# Explicit supervisor commands own their own lifecycle (e.g. `sleep infinity`
# for an exec container). Otherwise exec the request-scoped stdio server so it
# directly owns stdin/stdout and receives Docker's stop signal.
if [ "$#" -gt 0 ]; then
    exec "$@"
fi
exec openwrt-mcp
