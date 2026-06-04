FROM python:3.12-slim
RUN pip install --no-cache-dir watchfiles==1.2.0 PyYAML==6.0.1
COPY watch.py /app/watch.py
CMD ["python", "/app/watch.py"]
