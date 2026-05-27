# 🧠 Distributed Multi-Agent Consensus-Based Mind Map Generator
# AtlasMind: Distributed AI Mind Map Generator
> Transform any PDF or text document into an interactive knowledge graph using 7 microservices and 4 AI agents working in parallel.
A highly scalable, microservices-based application that uses Agentic AI to read large documents (PDFs, TXTs) and automatically extract interactive, visually stunning mind maps. 
---
Built with an enterprise-grade distributed architecture, this system utilizes a proxy-based LLM routing system to completely bypass API rate limits, while ensuring high-throughput document processing.
## Architecture Overview
## 🌟 Key Features
- **Agentic AI Processing**: Breaks down large documents into chunks and processes them in parallel using distributed AI agents.
- **Enterprise LLM Gateway (LiteLLM)**: Intelligently routes requests to free AI providers (NVIDIA NIM, Google Gemini). Automatically handles rate limits, retries, and fallback routing without crashing.
- **Microservices Architecture**: Fully containerized with Docker Compose, utilizing Redis for asynchronous message brokering.
- **Consensus Engine**: AI agents vote on the most important nodes and edges, filtering out noise and hallucination to build high-quality knowledge graphs.
- **Secure Authentication**: Built-in JWT (JSON Web Token) authentication with SQLite for secure, per-user history tracking.
- **Interactive UI**: A beautiful, glassmorphism-inspired React frontend for visualizing graphs, complete with PDF, PNG, and JSON export capabilities.
```
                        ┌─────────────────────────────────────────────────────────┐
                        │                    CLIENT BROWSER                       │
                        │              React + D3.js Force Graph                  │
                        └───────────────────────┬─────────────────────────────────┘
                                                │ HTTP / SSE / WebSocket
                        ┌───────────────────────▼─────────────────────────────────┐
                        │                  API GATEWAY                            │
                        │         FastAPI · Upload · Status · Graph               │
                        └───────────────────────┬─────────────────────────────────┘
                                                │ Redis Stream: document.ingested
                        ┌───────────────────────▼─────────────────────────────────┐
                        │            DOCUMENT INGESTION SERVICE                   │
                        │          PDF/TXT extraction · pdfplumber                │
                        └───────────────────────┬─────────────────────────────────┘
                                                │ Redis Stream: document.extracted
                        ┌───────────────────────▼─────────────────────────────────┐
                        │               CHUNKING SERVICE                          │
                        │    Sentence-aware sliding window · Overlap strategy     │
          │   CONCEPT     │  │RELATIONSHIP │  │SUMMARIZE  │  │SENTIMENT  │
          │    AGENT      │  │   AGENT     │  │  AGENT    │  │  AGENT    │
          │  (×2 replicas)│  │(×2 replicas)│  │           │  │           │
          └───────┬───────┘  └──────┬──────┘  └────┬──────┘  └────┬──────┘
                  └──────────────────┴──────────────┴──────────────┘
                                    │ Redis Stream: agent.results
                        ┌───────────▼─────────────────────────────────────────────┐
                        │              CONSENSUS ENGINE                           │
                        │  Weighted voting · Confidence merging · DLQ routing    │
                        └───────────────────────┬─────────────────────────────────┘
                                                │ Redis Stream: graph.built
                        ┌───────────────────────▼─────────────────────────────────┐
                        │               GRAPH BUILDER                             │
                        │          Neo4j (optional) · JSON export                 │
                        └─────────────────────────────────────────────────────────┘
                                        │
                        ┌───────────────▼────────────┐
                        │     REDIS (infrastructure) │
                        │  Streams · Pub/Sub · Cache  │
                        └────────────────────────────┘
```
## 🏗️ System Architecture
The application is broken down into several Dockerized microservices communicating via Redis streams:
1. **Frontend**: React + Vite UI.
2. **API Gateway**: FastAPI service handling user auth, history, and file uploads.
3. **LiteLLM Proxy**: Centralized router for all AI API calls.
4. **Document Ingestion & Chunking**: Extracts text from PDFs and chunks it intelligently.
5. **Orchestrator**: Manages the distributed pipeline and spawns tasks.
6. **Unified Agents**: Worker nodes that asynchronously ping the LLM to extract relationships.
7. **Consensus Engine**: Aggregates worker data, scores nodes/edges, and finalizes the graph.
---
## 🚀 Getting Started
## Distributed Systems Concepts Demonstrated
|
 Concept 
|
| Concept | Implementation |
| --- | --- |
| **Event-driven architecture** | Redis Streams as durable message queues between every service |
| **Fan-out parallelism** | One document chunk published once → consumed independently by 4 agent consumer groups |
| **Consumer groups** | All unified agents share a single consumer group; multiple replicas compete for messages (work-queue pattern) |
| **At-least-once delivery** | Messages only ACKed after successful processing; unACKed messages auto-reassigned on crash |
| **Dead Letter Queue** | After MAX_RETRIES exhausted, messages routed to `dead.letter.queue` stream |
| **Distributed locking** | Redis `SET NX EX` prevents duplicate consensus runs for the same document |
| **Eventual consistency** | Consensus engine waits for all agent results before merging; partial results tolerated |
| **Horizontal scalability** | Unified agents independently scalable: `docker compose up --scale unified-agent=4` |
| **Fault tolerance** | Exponential back-off retry on every agent; services restart automatically |
| **Real-time streaming** | SSE + WebSocket for live progress updates without polling overhead |
| **Idempotent operations** | Neo4j uses MERGE (not CREATE) — safe to reprocess same document |
| **Structured logging** | JSON logs from every service — ready for ELK/Loki aggregation |
---
## Technology Stack
| Layer | Technology | Rationale |
| --- | --- | --- |
| **Primary LLM** | **NVIDIA NIM (Llama 3.1)** | Massive free credits, enterprise throughput |
| **Fallback LLM** | **Google Gemini 2.0 Flash** | Generous free tier, excellent fallback reasoning |
| **LLM Gateway** | **LiteLLM Proxy** | Smart routing, rate-limit handling, Redis caching |
| Message Queue | **Redis Streams** | Lighter than Kafka, built-in consumer groups |
| API Framework | **FastAPI** | Async-native, auto-generated OpenAPI docs |
| Graph Storage | **Neo4j** (optional) | Purpose-built for knowledge graphs |
| Graph Cache | **Redis** | Sub-millisecond graph retrieval |
| Frontend | **React + D3.js** | D3 force simulation = best-in-class graph viz |
| State Management | **Zustand** | Minimal, hooks-based |
| Containerization | **Docker Compose** | Single-command deployment |
| Monitoring | **Prometheus + Grafana** | Optional profile |
### Free Tier Limits
| Provider | Models | Rate Limit | Key Required |
| --- | --- | --- | --- |
| **NVIDIA Build** | Llama 3.1 70B / 8B | High throughput | Yes (free credits) |
| **Google AI Studio** | Gemini 2.0 Flash | 15 RPM | Yes (free tier) |

> **Enterprise LiteLLM Gateway**: All AI requests route through a centralized LiteLLM proxy. The proxy automatically load balances requests, uses NVIDIA as the primary high-speed engine, and gracefully falls back to Gemini if rate-limited, completely eliminating crashes. An in-memory prompt-hash cache via Redis deduplicates calls for overlapping chunk windows.
---
## Project Structure
```
mindmap-system/
├── services/
│   ├── api_gateway/           # FastAPI entry point, SSE, WebSocket
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── document_ingestion/    # PDF/text extraction
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── chunking_service/      # Sentence-aware text splitter
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── agents/
│   │   ├── unified_agent/     # Extracts concepts, relations, sentiment, & summaries
│   │   ├── Dockerfile         # Dockerfile for unified agent worker
│   │   ├── requirements.txt
│   ├── consensus_engine/      # Weighted voting + conflict resolution
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   ├── graph_builder/         # Neo4j persistence + JSON export
│   │   ├── main.py
│   │   ├── requirements.txt
│   │   └── Dockerfile
│   └── frontend/              # React + D3.js SPA
│       ├── src/
│       │   ├── components/    # UploadView, ProcessingView, GraphView, Header
│       │   ├── hooks/         # useForceGraph (D3 integration)
│       │   ├── store/         # Zustand global state
│       │   └── utils/
│       ├── package.json
│       ├── vite.config.js
│       ├── Dockerfile
│       └── nginx.conf
├── shared/
│   ├── models/schemas.py      # Pydantic models shared by all services
│   └── utils/helpers.py       # Redis helpers, retry decorator, logging
├── infrastructure/
│   ├── monitoring/
│   │   ├── prometheus.yml
│   │   └── grafana/
│   └── nginx/
├── tests/
│   ├── unit/
│   │   ├── test_consensus.py  # Merge algorithm unit tests
│   │   └── test_chunker.py    # Text splitter unit tests
│   └── integration/
│       └── test_pipeline.py   # Full end-to-end pipeline test
├── docs/
│   ├── sample_document.txt    # ML/AI overview — ready to test
│   └── example_output.json    # Expected graph output
├── scripts/
│   └── manage.sh              # Convenience management script
├── docker-compose.yml
├── .env.example
└── README.md
```
---
## Quick Start
### Prerequisites
- [Docker](https://www.docker.com/products/docker-desktop/) and Docker Compose installed.
- Free API keys from:
  - [NVIDIA Build](https://build.nvidia.com/) (Primary high-throughput provider)
  - [Google AI Studio](https://aistudio.google.com/) (Fallback provider)
- Docker 24+ and Docker Compose v2
- At least one free API key (Gemini **or** Groq — both recommended)
- 4 GB RAM available for Docker
### Installation
### Step 1 — Get your free API keys
1. **Clone the repository**
   ```bash
   git clone https://github.com/your-username/CogniGraph.git
   cd CogniGraph
   ```
**NVIDIA Build** (primary — high throughput)
1. Visit [build.nvidia.com](https://build.nvidia.com/)
2. Create a free account and generate an API key.

**Google AI Studio** (fallback — excellent reasoning)
1. Visit [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **Create API Key** (Free tier: 15 RPM).

2. **Configure Environment Variables**
   Create a `.env` file in the root directory and add the following keys:
   ```env
   # AI Provider Keys
   NVIDIA_API_KEY=your_nvidia_api_key_here
   GEMINI_API_KEY=your_gemini_api_key_here

   # Internal Security
   LITELLM_MASTER_KEY=sk-mindmap-master-key-2025
   JWT_SECRET=super-secret-string-for-passwords
   # Database & Redis
   SQLITE_PATH=/app/data/mindmap.db
   REDIS_HOST=redis
   REDIS_PORT=6379
   ```
### Step 2 — Configure
3. **Build and Run the System**
   ```bash
   docker compose up --build -d
   ```
   *Note: The first build may take a few minutes as it downloads the LLM proxy and python dependencies.*
```bash
git clone <repo-url> mindmap-system
cd mindmap-system
4. **Access the Application**
   Open your browser and navigate to `http://localhost:3000`.
cp .env.example .env
# Edit .env — set at minimum GEMINI_API_KEY and GROQ_API_KEY
```
## 📖 Usage
1. **Sign Up / Log In**: Create an account on the local web interface.
2. **Upload a Document**: Drop a PDF or text file into the upload zone.
3. **Wait for Processing**: The system will automatically chunk, process, and map the document in the background.
4. **Interact & Export**: Drag nodes around to explore the graph, and use the export tools (Top Right) to download a PNG, PDF, or JSON of your mind map!
Your `.env` should look like:
```dotenv
NVIDIA_API_KEY=nvapi-...          # from build.nvidia.com
GEMINI_API_KEY=AIzaSy...          # from aistudio.google.com
LITELLM_MASTER_KEY=sk-proxy-...   # secure custom password
JWT_SECRET=super-secret-...       # secure custom password
```
## 🛡️ License
This project is open-source and available under the MIT License.
### Step 3 — Start all services
```bash
docker compose up -d --build
# Or:
chmod +x scripts/manage.sh && ./scripts/manage.sh start
```
### Step 4 — Open the UI
```
http://localhost:3000
```
### Step 5 — Try the sample document
```bash
./scripts/manage.sh demo
```
---
## Detailed Setup
### Environment Variables
| Variable | Default | Description |
| --- | --- | --- |
| `NVIDIA_API_KEY` | **required** | NVIDIA NIM API key (primary LLM) |
| `GEMINI_API_KEY` | **required** | Google Gemini API key (fallback LLM) |
| `LITELLM_MASTER_KEY` | `sk-mindmap-master-key-2025` | LiteLLM Proxy security token |
| `JWT_SECRET` | `change-me-in-production...` | Secret key for JWT auth encryption |
| `CHUNK_SIZE` | `1500` | Characters per chunk |
| `CHUNK_OVERLAP` | `200` | Overlap between consecutive chunks |
| `VOTE_THRESHOLD` | `1` | Min agent mentions for concept acceptance |
| `CONF_THRESHOLD` | `0.45` | Min confidence score for concept acceptance |
| `EDGE_CONF_THRESHOLD` | `0.4` | Min confidence for relationship acceptance |
| `MAX_RETRIES` | `3` | Agent retry attempts before DLQ |
| `NEO4J_ENABLED` | `false` | Enable Neo4j persistence |
### Enterprise LiteLLM Gateway
All LLM requests flow through a central LiteLLM Proxy container, providing intelligent routing:
```
Agent request
     │
     ▼
┌─────────────────────────────────────────────┐
│  1. LiteLLM Proxy / Redis Cache             │ → cache hit: return instantly, no API call
└─────────────────────┬───────────────────────┘
                      │ cache miss
                      ▼
┌─────────────────────────────────────────────┐
│  2. NVIDIA NIM (llama-3.1-70b)              │ → success: cache + return
│     High throughput, primary extraction     │
└─────────────────────┬───────────────────────┘
                      │ rate-limited or error
                      ▼
┌─────────────────────────────────────────────┐
│  3. Google Gemini (gemini-2.0-flash)        │ → success: cache + return
│     Fallback provider, highly reliable      │
└─────────────────────────────────────────────┘
```
**Rate limit handling**: an in-process sliding-window counter tracks requests per provider in the last 60 seconds. If a provider is full, the cascade skips it immediately without wasting a network call.
**Cache**: prompt text is hashed (SHA-256, first 20 chars). Identical prompts — common with overlapping chunk windows — are served from memory. Cache evicts LRU entries at 400 items.
**Batching tip**: if you're hitting rate limits with large documents, increase `CHUNK_SIZE` in `.env` to reduce total chunk count (and thus fewer LLM calls per document).
Agents are independently scalable. To process large documents faster:
```bash
# Run 4 unified agents in parallel
docker compose up -d --scale unified-agent=4
```
Redis Streams consumer groups automatically distribute work across all instances.
### Enable Neo4j
```bash
# Start with Neo4j
docker compose --profile neo4j up -d
# Set in .env
NEO4J_ENABLED=true
# Access Neo4j Browser
open http://localhost:7474
# Login: neo4j / mindmap123
```
### Enable Monitoring (Prometheus + Grafana)
```bash
./scripts/manage.sh start-monitoring
# Prometheus: http://localhost:9090
# Grafana:    http://localhost:3001  (admin/admin)
```
---
## API Reference
### Upload Document
```http
POST /api/v1/documents/upload
Content-Type: multipart/form-data
file: <PDF|TXT|MD>
Response: { "document_id": "uuid", "filename": "...", "status": "queued" }
```
### Check Status
```http
GET /api/v1/documents/{document_id}/status
Response: {
  "status": "processing",
  "progress_pct": 67.5,
  "total_chunks": 8,
  "agent_results_received": 21
}
```
### Get Knowledge Graph
```http
GET /api/v1/documents/{document_id}/graph
Response: {
  "nodes": [{ "id": "machine_learning", "label": "Machine Learning", ... }],
  "edges": [{ "source": "deep_learning", "target": "machine_learning", ... }],
  "global_summary": "...",
  "stats": { ... }
}
```
### Stream Progress (SSE)
```javascript
const source = new EventSource(`/api/v1/documents/${docId}/stream`)
source.onmessage = (e) => console.log(JSON.parse(e.data))
```
### WebSocket
```javascript
const ws = new WebSocket(`ws://localhost:8000/ws/${docId}`)
ws.onmessage = (e) => console.log(JSON.parse(e.data))
```
Full interactive API docs: `http://localhost:8000/docs`
---
## Consensus Algorithm Deep Dive
### Concept Merging
```
For each unique concept ID across all agent outputs:
  1. Count mentions (vote weight)
  2. Compute average confidence
  3. Apply multi-mention boost: conf × (1 + 0.1 × mentions)
  4. Accept if: mentions >= VOTE_THRESHOLD AND conf >= CONF_THRESHOLD
  5. Resolve label conflict: take most-frequent label
  6. Merge sentiment: average across all agent outputs
  7. Sort by final confidence (descending)
```
### Relationship Merging
```
For each (source, target, relation_type) triple:
  1. Filter: both endpoints must be accepted concepts
  2. Filter: source != target (no self-loops)
  3. Filter: average confidence >= EDGE_CONF_THRESHOLD
  4. Deduplicate: keep highest-confidence direction for each node pair
  5. Weight = min(avg_confidence × mention_count, 1.0)
```
### Global Summary Synthesis
```
Collect all chunk-level summaries from Summarization Agent
Sort by chunk index (preserves document flow)
Prompt Claude to synthesize into 3-5 sentence document summary
Fallback: concatenate first 3 chunk summaries on LLM error
```
---
## Output Schema
```json
{
  "document_id": "uuid",
  "nodes": [
    {
      "id": "machine_learning",
      "label": "Machine Learning",
      "category": "TECHNOLOGY",
      "confidence": 0.97,
      "mention_count": 8,
      "sentiment": 0.45
    }
  ],
  "edges": [
    {
      "source": "deep_learning",
      "target": "machine_learning",
      "relation_type": "is_a",
      "label": "is a subset of",
      "confidence": 0.95,
      "weight": 0.95
    }
  ],
  "global_summary": "...",
  "total_chunks_processed": 6,
  "consensus_method": "weighted_voting_confidence_merging",
  "stats": {
    "total_agent_results": 24,
    "concepts_before_merge": 87,
    "concepts_after_merge": 22,
    "relationships_before_merge": 54,
    "relationships_after_merge": 12
  }
}
```
### Relationship Types
| Type | Meaning |
| --- | --- |
| `is_a` | Taxonomy / classification |
| `part_of` | Composition / containment |
| `causes` | Causal relationship |
| `enables` | X makes Y possible |
| `requires` | Dependency |
| `uses` | Operational / applied |
| `implements` | Realization |
| `related_to` | General co-occurrence |
| `contrasts_with` | Opposition / alternative |
| `produces` | Output / result |
---
## Running Tests
```bash
# Unit tests (no running stack required)
pip install pytest
pytest tests/unit/ -v
# Integration test (stack must be running)
./scripts/manage.sh start
python tests/integration/test_pipeline.py
```
---
## Useful Commands
```bash
# View logs for a specific service
./scripts/manage.sh logs concept-agent
./scripts/manage.sh logs consensus-engine
# Check all service status
./scripts/manage.sh status
# Inspect Redis Streams
docker exec -it $(docker ps -q -f name=redis) redis-cli
> XLEN chunks.ready          # pending chunks
> XLEN agent.results         # accumulated results
> XLEN dead.letter.queue     # failed messages
# Check a job state
docker exec -it $(docker ps -q -f name=redis) redis-cli get "job:state:<document_id>"
# Stop everything and wipe volumes
./scripts/manage.sh clean
```
---
## Frontend Features
| Feature | Implementation |
| --- | --- |
| **Drag & drop upload** | react-dropzone with file type validation |
| **Live pipeline progress** | SSE stream → progress ring + stage indicator |
| **Force-directed graph** | D3.js simulation with configurable forces |
| **Zoom & pan** | D3 zoom behavior, min 0.1×, max 4× |
| **Node hover** | Highlights connected nodes, dims unrelated |
| **Click for detail** | Sidebar panel with confidence, sentiment, relationships |
| **Category filter** | Chips to filter visible node categories |
| **Search** | Dims non-matching nodes in real time |
| **Sentiment rings** | Dashed rings on nodes: green=positive, red=negative |
| **Confidence badges** | Percentage displayed inside each node |
| **Relationship arrows** | Color-coded arrowhead markers per relation type |
| **Edge labels** | Displayed for high-confidence (>0.65) relationships |
---
## Extending the System
### Adding a New Agent
1. Create `services/agents/my_agent/main.py`
2. Inherit from `BaseAgent`
3. Implement `process_chunk(data)` returning the `AgentOutput` schema
4. Add service to `docker-compose.yml`
5. Update consensus engine weights in `AGENT_WEIGHTS`
```python
from base_agent import BaseAgent
class MyAgent(BaseAgent):
    def __init__(self):
        super().__init__(agent_type="my_agent")
    async def process_chunk(self, data):
        text = data.get("text", "")
        # ... your logic ...
        return {
            "agent_type": "my_agent",
            "document_id": data["document_id"],
            "chunk_id": data["chunk_id"],
            "chunk_index": int(data["chunk_index"]),
            "total_chunks": int(data["total_chunks"]),
            "concepts": [],
            "relationships": [],
            "confidence_overall": 0.8,
        }
```

