FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    libpq-dev gcc python3-dev \
    && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir mcp fastmcp psycopg2

COPY mcp_postgres.py /app/mcp_postgres.py

EXPOSE 8000

ENTRYPOINT ["python", "/app/mcp_postgres.py"]
