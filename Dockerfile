# syntax=docker/dockerfile:1
FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN useradd --create-home --uid 10001 --shell /usr/sbin/nologin openwrt \
    && mkdir -p /app/log /app/keys \
    && chown -R openwrt:openwrt /app

WORKDIR /app

# CI builds and tests this exact wheel before building the image.
COPY dist/*.whl /tmp/openwrt-mcp.whl
RUN python -m pip install --no-cache-dir /tmp/openwrt-mcp.whl \
    && rm /tmp/openwrt-mcp.whl \
    && python -m pip check

USER openwrt
CMD ["openwrt-mcp"]
