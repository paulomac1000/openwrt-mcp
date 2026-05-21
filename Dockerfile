# OpenWRT MCP Server
# Model Context Protocol server for OpenWRT router management

FROM python:3.14-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

RUN useradd --create-home --shell /bin/bash openwrt

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pyproject.toml .
COPY src/ ./src/
RUN pip install --no-cache-dir -e .

RUN mkdir -p /app/log && chown -R openwrt:openwrt /app

EXPOSE 9094 9095 9096

USER openwrt
CMD ["openwrt-mcp"]
