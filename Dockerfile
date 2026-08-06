# syntax=docker/dockerfile:1
FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin openwrt \
    && mkdir -p /app/log /app/keys \
    && chown -R openwrt:openwrt /app

WORKDIR /app

# CI generates the hashed lock, builds and tests this exact wheel, then builds the image.
COPY requirements-runtime.lock /tmp/requirements-runtime.lock
COPY dist/*.whl /tmp/openwrt-mcp.whl
RUN python -m pip install --no-cache-dir --require-hashes -r /tmp/requirements-runtime.lock \
    && python -m pip install --no-cache-dir --no-deps /tmp/openwrt-mcp.whl \
    && rm /tmp/requirements-runtime.lock /tmp/openwrt-mcp.whl \
    && python -m pip check

USER openwrt
CMD ["openwrt-mcp"]
