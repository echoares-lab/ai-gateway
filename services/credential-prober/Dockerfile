FROM python:3.14-slim@sha256:cea0e6040540fb2b965b6e7fb5ffa00871e632eef63719f0ea54bca189ce14a6
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
