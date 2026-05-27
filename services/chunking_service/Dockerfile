FROM python:3.11-slim
WORKDIR /app
COPY services/chunking_service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY shared /app/shared
COPY services/chunking_service /app
CMD ["python", "main.py"]
