FROM python:3.12-slim

ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/your-org/ai-gateway" \
      org.opencontainers.image.revision=$GIT_SHA \
      ai-gateway.service="litellm-reloader" \
      ai-gateway.environment=$ENVIRONMENT

RUN pip install --no-cache-dir watchfiles==1.2.0 PyYAML==6.0.1
COPY watch.py /app/watch.py
CMD ["python", "/app/watch.py"]
