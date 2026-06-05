FROM python:3.11-slim
WORKDIR /app
RUN pip install fastapi uvicorn
COPY services/docs-server/main.py .
COPY docs/openapi /app/docs/openapi
EXPOSE 8000
CMD ["python", "main.py"]
