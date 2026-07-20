FROM python:3.11-slim@sha256:db3ff2e1800a8581e2c48a27c3995339d47bdf046da21c7627accd3d51053a93
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
