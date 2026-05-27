FROM python:3.11-slim

WORKDIR /app

# Install system deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc curl && rm -rf /var/lib/apt/lists/*

# Install ALL Python dependencies (combined from all services)
COPY services/api_gateway/requirements.txt /tmp/req_gateway.txt
COPY services/document_ingestion/requirements.txt /tmp/req_ingestion.txt
COPY services/chunking_service/requirements.txt /tmp/req_chunking.txt
COPY services/agents/requirements.txt /tmp/req_agents.txt
COPY services/consensus_engine/requirements.txt /tmp/req_consensus.txt
COPY services/graph_builder/requirements.txt /tmp/req_graph.txt

RUN pip install --no-cache-dir \
    -r /tmp/req_gateway.txt \
    -r /tmp/req_ingestion.txt \
    -r /tmp/req_chunking.txt \
    -r /tmp/req_agents.txt \
    -r /tmp/req_consensus.txt \
    -r /tmp/req_graph.txt


# Copy shared modules
COPY shared /app/shared

# Copy ALL service code (monolith — all workers run in this single container)
COPY services/api_gateway /app
COPY services/document_ingestion /app/document_ingestion
COPY services/chunking_service /app/chunking_service
COPY services/agents /app/agents
COPY services/consensus_engine /app/consensus_engine
COPY services/graph_builder /app/graph_builder
COPY services/orchestrator /app/orchestrator

# Create upload and data directories
RUN mkdir -p /app/uploads /app/data /app/graphs

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=30s \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
