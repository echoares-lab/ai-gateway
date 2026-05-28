FROM python:3.12-slim
RUN pip install --no-cache-dir fastapi uvicorn[standard] httpx
WORKDIR /app
COPY translator.py .
CMD ["uvicorn", "translator:app", "--host", "0.0.0.0", "--port", "4000"]
