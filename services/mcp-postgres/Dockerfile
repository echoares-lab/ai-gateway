FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/echoares-lab/ai-gateway" \
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
