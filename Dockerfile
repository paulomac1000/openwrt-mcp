# OpenWRT MCP Server
# Model Context Protocol server for OpenWRT router management

FROM python:3.11-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY server.py .
COPY tools/ ./tools/
COPY conftest.py ./
COPY tests/ ./tests/

RUN printf '#!/bin/bash\npython server.py\n' > /app/start.sh && chmod +x /app/start.sh

# Ports: 9094 (health), 9095 (MCP SSE), 9096 (REST API)
EXPOSE 9094 9095 9096

CMD ["/app/start.sh"]
