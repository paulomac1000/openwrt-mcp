#!/bin/sh
set -eu

if [ "$#" -gt 0 ]; then
    exec "$@"
fi

child=
terminate() {
    [ -n "$child" ] || exit 143
    kill -TERM "$child" 2>/dev/null || true
    n=0
    while kill -0 "$child" 2>/dev/null && [ "$n" -lt 10 ]; do
        sleep 0.1
        n=$((n + 1))
    done
    kill -KILL "$child" 2>/dev/null || true
    wait "$child" 2>/dev/null || true
    exit 143
}
trap terminate TERM

openwrt-mcp &
child=$!
wait "$child"
