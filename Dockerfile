# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ARG SOURCE_REVISION
ARG APP_VERSION
ARG WHEEL_SHA256
LABEL org.opencontainers.image.source="https://github.com/paulomac1000/openwrt-mcp" \
      org.opencontainers.image.revision="${SOURCE_REVISION}" \
      org.opencontainers.image.version="${APP_VERSION}" \
      io.openwrt-mcp.wheel.sha256="${WHEEL_SHA256}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# Apply Debian security updates while retaining the pinned base-image digest.
# The final artifact is still re-verified by CI and scanned before promotion.
RUN apt-get update \
    && apt-get upgrade -y --no-install-recommends \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin openwrt \
    && mkdir -p /app/log /app/keys \
    && chown -R openwrt:openwrt /app

WORKDIR /app
COPY requirements-runtime.lock /tmp/requirements-runtime.lock
COPY dist/*.whl /tmp/wheels/
RUN set -eu; \
    wheel_count="$(find /tmp/wheels -maxdepth 1 -type f -name '*.whl' | wc -l)"; \
    test "$wheel_count" -eq 1; \
    wheel="$(find /tmp/wheels -maxdepth 1 -type f -name '*.whl' -print -quit)"; \
    python -c 'import re, sys; sys.exit(not (re.fullmatch(r"[0-9a-f]{40}", sys.argv[1]) and re.fullmatch(r"[0-9a-f]{64}", sys.argv[2]) and sys.argv[3]))' "$SOURCE_REVISION" "$WHEEL_SHA256" "$APP_VERSION"; \
    printf '%s  %s\n' "$WHEEL_SHA256" "$wheel" | sha256sum -c -; \
    python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements-runtime.lock; \
    python -m pip install --no-cache-dir --no-deps "$wheel"; \
    python -m pip check; \
    python -c 'import sys; from importlib.metadata import version; from openwrt_mcp import __version__; sys.exit(not (version("openwrt-mcp") == __version__ == sys.argv[1]))' "$APP_VERSION"; \
    install -d -m 0755 /usr/local/share/openwrt-mcp; \
    python -c 'import json, sys; print(json.dumps(dict(zip(("revision", "wheel_sha256", "version"), sys.argv[1:], strict=True))))' "$SOURCE_REVISION" "$WHEEL_SHA256" "$APP_VERSION" > /usr/local/share/openwrt-mcp/provenance.json; \
    rm -rf /tmp/requirements-runtime.lock /tmp/wheels

COPY docker-entrypoint.sh /usr/local/bin/docker-entrypoint
RUN chmod 0755 /usr/local/bin/docker-entrypoint

USER openwrt
STOPSIGNAL SIGTERM
# No image HEALTHCHECK: Docker probes cannot truthfully represent stdio MCP or
# router readiness. Deployment mode owns container and readiness lifecycle.
ENTRYPOINT ["/usr/local/bin/docker-entrypoint"]
