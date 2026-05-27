FROM python:3.11-slim
WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends gcc curl && \
    rm -rf /var/lib/apt/lists/*

# Build context is repo root (mindmap-fixed/) — all paths relative to that
COPY services/agents/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Shared library
COPY shared /app/shared

# Base infrastructure (used by all agents)
COPY services/agents/base_agent.py  /app/base_agent.py
COPY services/agents/llm_client.py  /app/llm_client.py

# Unified agent (primary — 1 call per chunk)
COPY services/agents/unified_agent  /app/unified_agent

# Individual agents kept for compatibility / optional use
COPY services/agents/concept_agent       /app/concept_agent
COPY services/agents/relationship_agent  /app/relationship_agent
COPY services/agents/summarization_agent /app/summarization_agent
COPY services/agents/sentiment_agent     /app/sentiment_agent

HEALTHCHECK --interval=60s --timeout=10s --start-period=20s \
    CMD python -c "import redis; r = redis.Redis(host='redis'); r.ping()" || exit 1

CMD ["python", "/app/unified_agent/main.py"]
