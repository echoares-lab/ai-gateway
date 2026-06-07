FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/your-org/ai-gateway" \
      org.opencontainers.image.revision=$GIT_SHA \
      ai-gateway.service="mcp-postgres" \
      ai-gateway.environment=$ENVIRONMENT

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir mcp fastmcp psycopg2

COPY mcp_postgres.py /app/mcp_postgres.py

EXPOSE 8000

ENTRYPOINT ["python", "/app/mcp_postgres.py"]
