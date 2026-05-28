FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi==0.115.12 "uvicorn[standard]==0.34.3" httpx==0.28.1
WORKDIR /app
COPY translator.py .
HEALTHCHECK --interval=30s --timeout=5s --retries=3 CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:4000/health')" || exit 1
CMD ["uvicorn", "translator:app", "--host", "0.0.0.0", "--port", "4000"]
