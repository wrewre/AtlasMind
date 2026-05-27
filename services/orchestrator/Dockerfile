FROM python:3.11-slim
WORKDIR /app
RUN pip install --no-cache-dir redis httpx structlog
COPY services/orchestrator/main.py ./main.py
CMD ["python", "main.py"]
