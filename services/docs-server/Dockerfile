FROM python:3.11-slim
ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/echoares-lab/ai-gateway" \
      org.opencontainers.image.revision=$GIT_SHA \
      ai-gateway.service="docs-server" \
      ai-gateway.environment=$ENVIRONMENT

WORKDIR /app
RUN pip install fastapi uvicorn
COPY services/docs-server/main.py .
COPY docs/openapi /app/docs/openapi
EXPOSE 8000
CMD ["python", "main.py"]
