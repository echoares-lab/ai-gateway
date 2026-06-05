FROM python:3.12-slim
WORKDIR /app
RUN pip install --no-cache-dir psycopg2-binary
COPY prober.py notifier.py ./
CMD ["python", "-u", "prober.py"]
