FROM python:3.12-slim
RUN # bust cache
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.3" httpx==0.28.1 \
    "redis[asyncio]==5.3.0" pytest==8.3.5 pytest-asyncio==0.24.0 pytest-xdist==3.6.1 prometheus-client==0.21.1 \
    PyYAML==6.0.2 fakeredis==2.26.2 pydantic==2.10.6 psycopg2-binary==2.9.10 respx==0.22.0 websockets==16.0
WORKDIR /app
COPY main.py admin_api.py workspace_rules.py gemini-model-map.json conftest.py test_translator*.py test_translator_admin_api.py ./
COPY core ./core/
COPY providers ./providers/
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4000/health')" || exit 1
CMD uvicorn main:app --host 0.0.0.0 --port 4000 --workers ${WEB_CONCURRENCY:-1}
