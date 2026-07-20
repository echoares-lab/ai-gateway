FROM python:3.12-slim@sha256:57cd7c3a7a273101a6485ba99423ee568157882804b1124b4dd04266317710de
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
