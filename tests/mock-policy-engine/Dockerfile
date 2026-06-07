FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/your-org/ai-gateway" \
      org.opencontainers.image.revision=$GIT_SHA \
      ai-gateway.service="policy-engine" \
      ai-gateway.environment=$ENVIRONMENT

WORKDIR /app
RUN pip install --no-cache-dir fastapi "uvicorn[standard]"
COPY app.py .
EXPOSE 8080
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8080"]
