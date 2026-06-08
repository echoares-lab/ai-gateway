FROM python:3.12-slim
ARG GIT_SHA=unknown
ARG ENVIRONMENT=production
LABEL org.opencontainers.image.source="https://github.com/echoares-lab/ai-gateway" \
      org.opencontainers.image.revision=$GIT_SHA \
      ai-gateway.service="credential-prober" \
      ai-gateway.environment=$ENVIRONMENT

WORKDIR /app
RUN pip install --no-cache-dir psycopg2-binary
COPY credential_probe.py prober.py notifier.py ./
CMD ["python", "-u", "prober.py"]
