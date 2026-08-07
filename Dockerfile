# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ARG SOURCE_REVISION=unknown
LABEL org.opencontainers.image.source="https://github.com/paulomac1000/openwrt-mcp" \
      org.opencontainers.image.revision="${SOURCE_REVISION}"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

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
    python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements-runtime.lock; \
    python -m pip install --no-cache-dir --no-deps "$wheel"; \
    python -m pip check; \
    rm -rf /tmp/requirements-runtime.lock /tmp/wheels

USER openwrt
CMD ["openwrt-mcp"]
