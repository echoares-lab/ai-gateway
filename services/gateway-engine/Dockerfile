FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/your-org/ai-gateway" \
      org.opencontainers.image.revision=$GIT_SHA \
      ai-gateway.service="gateway-engine" \
      ai-gateway.environment=$ENVIRONMENT

RUN # bust cache
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.3" httpx==0.28.1 \
    "redis[asyncio]==5.3.0" pytest==8.3.5 pytest-asyncio==0.24.0 pytest-xdist==3.6.1 prometheus-client==0.21.1 \
    PyYAML==6.0.2 fakeredis==2.26.2 pydantic==2.10.6 psycopg2-binary==2.9.10 respx==0.22.0 websockets==16.0

WORKDIR /app
COPY main.py admin_api.py workspace_rules.py gemini-model-map.json conftest.py pytest.ini test_gateway_engine*.py test_token_analytics.py ./
COPY core ./core/
COPY orchestrator ./orchestrator/
COPY providers ./providers/
COPY utils ./utils/

ENV GATEWAY_ENGINE_PORT=4000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
    CMD ["sh", "-c", "python -c \"import urllib.request, os; port = os.getenv('GATEWAY_ENGINE_PORT', '4000'); urllib.request.urlopen(f'http://localhost:{port}/health')\""]

CMD ["sh", "-c", "uvicorn main:app --host 0.0.0.0 --port ${GATEWAY_ENGINE_PORT} --workers ${WEB_CONCURRENCY:-1}"]
