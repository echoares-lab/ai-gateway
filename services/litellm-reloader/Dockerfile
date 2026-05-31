FROM python:3.12-slim
RUN pip install --no-cache-dir watchfiles==1.2.0
COPY watch.py /app/watch.py
CMD ["python", "/app/watch.py"]
