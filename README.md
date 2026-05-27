# 🧠 AtlasMind — Distributed AI Mind Map Generator

> Transform any PDF or text document into an interactive knowledge graph using a distributed multi-agent AI pipeline.

[![Live Demo](https://img.shields.io/badge/Live%20Demo-Railway-blueviolet)](https://your-frontend-url.up.railway.app)
[![GitHub](https://img.shields.io/badge/GitHub-AtlasMind-black)](https://github.com/wrewre/AtlasMind)

---

## 🌟 Key Features

- **Agentic AI Processing**: Breaks large documents into chunks and processes them in parallel using a ReAct + Critic agent loop.
- **Distributed Pipeline**: 6 microservices communicate exclusively via Redis Streams — fully decoupled, fault-tolerant, at-least-once delivery.
- **Consensus Engine**: Weighted voting across all agent results filters noise and hallucination before building the final graph.
- **Secure Authentication**: JWT auth with per-user document history (SQLite).
- **Real-time Progress**: SSE streaming shows live pipeline progress directly in the browser.
- **Interactive UI**: Glassmorphism React + D3.js force-directed graph with zoom, pan, search, category filters, and PNG/PDF/JSON export.
- **Cloud Deployed**: Hosted on Railway — accessible worldwide 24/7 with zero infrastructure management.

---

## 🏗️ Architecture Overview

```
                    ┌──────────────────────────────┐
                    │         CLIENT BROWSER        │
                    │     React + D3.js Frontend    │
                    └──────────────┬───────────────┘
                                   │ HTTPS / SSE
                    ┌──────────────▼───────────────┐
                    │         API GATEWAY           │
                    │  FastAPI · Auth · Upload · SSE│
                    │  + All Workers (Monolith Mode)│
                    └──────────────┬───────────────┘
                                   │ Redis Streams
                    ┌──────────────▼───────────────┐
                    │  document.ingested stream     │
                    │  → Document Ingestion Worker  │ (pdfplumber)
                    └──────────────┬───────────────┘
                                   │ document.extracted stream
                    ┌──────────────▼───────────────┐
                    │     Orchestrator Worker       │ (decides strategy per doc)
                    │     Chunking Service Worker   │ (sentence-aware splitter)
                    └──────────────┬───────────────┘
                                   │ chunks.ready stream (fan-out)
                    ┌──────────────▼───────────────┐
                    │      Unified Agent Worker     │
                    │  ReAct Loop + Critic Filter   │
                    │  Concepts · Relations · Senti │
                    └──────────────┬───────────────┘
                                   │ agent.results stream
                    ┌──────────────▼───────────────┐
                    │     Consensus Engine Worker   │
                    │  Weighted voting · Merging    │
                    └──────────────┬───────────────┘
                                   │ graph.built stream
                    ┌──────────────▼───────────────┐
                    │     Graph Builder Worker      │
                    │  Redis cache · JSON export    │
                    └──────────────────────────────┘
                                   │
                    ┌──────────────▼───────────────┐
                    │     REDIS (Infrastructure)    │
                    │  Streams · Pub/Sub · Cache    │
                    └──────────────────────────────┘
```

### Deployment Architecture (Railway)

```
Railway Project
├── 🌐 Frontend Service    (React + Nginx)
├── ⚙️  API Gateway Service (FastAPI + all 6 workers in one container)
└── 🗄️  Redis Database
```

> **Note on Monolith Deployment**: All 6 background workers (Document Ingestion, Chunking, Orchestrator, Unified Agent, Consensus Engine, Graph Builder) run as concurrent `asyncio` tasks inside the API Gateway container. The internal communication via Redis Streams is **completely unchanged** — each worker is still fully decoupled and communicates only through message queues. This pattern is intentional for cost-efficient cloud deployment on Railway's free tier.

---

## 📐 Distributed Systems Concepts Demonstrated

| Concept | Implementation |
| --- | --- |
| **Event-driven architecture** | Redis Streams as durable message queues between every service |
| **Consumer groups** | Unified agents share a single consumer group; multiple replicas compete for messages (work-queue pattern) |
| **At-least-once delivery** | Messages only ACKed after successful processing; unACKed messages auto-reassigned on crash |
| **Dead Letter Queue** | After MAX_RETRIES exhausted, messages routed to `dead.letter.queue` stream |
| **Distributed locking** | Redis `SET NX EX` prevents duplicate consensus runs for the same document |
| **Eventual consistency** | Consensus engine waits for all agent results before merging; partial results tolerated |
| **Horizontal scalability** | Unified agents independently scalable: `docker compose up --scale unified-agent=4` |
| **Fault tolerance** | Exponential back-off retry on every agent; workers auto-restart on crash |
| **Real-time streaming** | SSE + WebSocket for live progress updates without polling overhead |
| **ReAct Agentic Loop** | Unified agent: Think → Act → Observe → Retry if confidence too low |
| **Structured logging** | JSON logs from every service — ready for ELK/Loki aggregation |

---

## 🔧 Technology Stack

| Layer | Technology | Rationale |
| --- | --- | --- |
| **Primary LLM** | **NVIDIA NIM (Llama 3.1)** | Massive free credits, enterprise throughput |
| **Fallback LLM** | **Google Gemini 2.0 Flash** | Generous free tier, excellent reasoning |
| **Message Queue** | **Redis Streams** | Lighter than Kafka, built-in consumer groups |
| **API Framework** | **FastAPI** | Async-native, auto-generated OpenAPI docs |
| **Graph Cache** | **Redis** | Sub-millisecond graph retrieval |
| **Frontend** | **React + D3.js** | D3 force simulation = best-in-class graph viz |
| **State Management** | **Zustand** | Minimal, hooks-based |
| **Auth** | **JWT + SQLite** | Secure per-user history |
| **Containerization** | **Docker Compose** | Single-command local deployment |
| **Cloud Hosting** | **Railway** | Free tier, automatic GitHub deploys |

---

## 🚀 Deployment Guide (Railway — Live on the Internet)

### Prerequisites
- A [Railway](https://railway.app/) account (free, sign up with GitHub)
- Free API keys from:
  - [NVIDIA Build](https://build.nvidia.com/) — Primary LLM provider
  - [Google AI Studio](https://aistudio.google.com/apikey) — Fallback LLM provider

### Step 1 — Fork / Clone the Repo
```bash
git clone https://github.com/wrewre/AtlasMind.git
```

### Step 2 — Create a Railway Project
1. Go to [railway.app](https://railway.app/) → **New Project**
2. Click **Deploy from GitHub Repo** → select `AtlasMind`
3. Railway will detect the repo. **Don't deploy yet.**

### Step 3 — Add Redis
- Click **`+ Add`** → **Database** → **Add Redis**

### Step 4 — Deploy the API Gateway (Backend + All Workers)
- Click **`+ Add`** → **GitHub Repo** → `AtlasMind`
- Go to **Settings → Build** → set Builder to `Dockerfile`
- Set **Dockerfile Path** to: `services/api_gateway/Dockerfile`
- Rename the service to **"API Gateway"**
- Go to **Variables** and add:
  ```
  NVIDIA_API_KEY=your_nvidia_key_here
  GEMINI_API_KEY=your_gemini_key_here
  JWT_SECRET=any-long-random-string
  REDIS_URL=${{Redis.REDIS_URL}}
  ```
- Click **Deploy**

### Step 5 — Deploy the Frontend
- Click **`+ Add`** → **GitHub Repo** → `AtlasMind`
- Go to **Settings → Build** → set Builder to `Dockerfile`
- Set **Dockerfile Path** to: `services/frontend/Dockerfile`
- Rename the service to **"Frontend"**
- Go to **Settings → Networking** → **Generate Domain** → copy the URL
- Go to **Variables** and add:
  ```
  VITE_API_URL=https://your-api-gateway-url.up.railway.app
  ```
- Click **Deploy**

### Step 6 — Link API Gateway Domain
- Click your **API Gateway** service → **Settings → Networking → Generate Domain**
- Copy that URL and paste it as the value of `VITE_API_URL` in your **Frontend** variables
- Redeploy the Frontend

### Step 7 — Open Your Live Site! 🎉
Click the Frontend's generated domain link. Your site is now live worldwide!

---

## 💻 Local Development Guide

### Prerequisites
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed
- 4 GB RAM available for Docker

### Step 1 — Get Free API Keys
**NVIDIA Build** (primary provider):
1. Visit [build.nvidia.com](https://build.nvidia.com/)
2. Create a free account → generate API key

**Google AI Studio** (fallback):
1. Visit [aistudio.google.com/apikey](https://aistudio.google.com/apikey)
2. Click **Create API Key**

### Step 2 — Configure Environment
```bash
git clone https://github.com/wrewre/AtlasMind.git
cd AtlasMind
cp .env.example .env
```
Edit `.env`:
```dotenv
NVIDIA_API_KEY=nvapi-...
GEMINI_API_KEY=AIzaSy...
JWT_SECRET=super-secret-random-string
```

### Step 3 — Run Everything
```bash
docker compose up --build
```

### Step 4 — Open the UI
```
http://localhost:80
```

---

## 📖 Usage

1. **Sign Up / Log In** — Create an account on the web interface.
2. **Upload a Document** — Drop a PDF, TXT, or Markdown file into the upload zone.
3. **Watch it Process** — A live progress bar shows real-time pipeline activity via SSE.
4. **Explore the Graph** — Drag nodes, zoom, pan, use category filters and the search bar.
5. **Export** — Download your mind map as PNG, PDF, or raw JSON.

---

## 🔌 API Reference

### Authentication
```http
POST /api/auth/register     { "username": "...", "password": "..." }
POST /api/auth/login        { "username": "...", "password": "..." }
GET  /api/auth/me           (Bearer token required)
```

### Document Pipeline
```http
POST /api/v1/documents/upload         (multipart/form-data, file field)
GET  /api/v1/documents/{id}/status    → { status, progress_pct, total_chunks }
GET  /api/v1/documents/{id}/graph     → { nodes, edges, global_summary, stats }
GET  /api/v1/documents/{id}/stream    → SSE event stream (real-time progress)
GET  /api/v1/history                  → User's document history
```

### Interactive API Docs
```
https://your-api-gateway.up.railway.app/docs
```

---

## 📊 Output Schema

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
      "confidence": 0.95
    }
  ],
  "global_summary": "...",
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

## 🗂️ Project Structure

```
AtlasMind/
├── services/
│   ├── api_gateway/           # FastAPI entry point + Monolith workers launcher
│   │   ├── main.py            # FastAPI app + lifespan worker boot
│   │   ├── workers.py         # Launches all 6 workers as asyncio tasks
│   │   ├── auth.py            # JWT authentication
│   │   ├── database.py        # SQLite history management
│   │   └── Dockerfile         # Monolith Dockerfile (copies all services)
│   ├── document_ingestion/    # PDF/TXT/MD text extraction (pdfplumber)
│   ├── chunking_service/      # Sentence-aware sliding window chunker
│   ├── agents/
│   │   ├── unified_agent/     # ReAct + Critic agent (concepts, relations, sentiment)
│   │   ├── base_agent.py      # Base class with retry, DLQ, timeout logic
│   │   └── llm_client.py      # HTTP client for NVIDIA/Gemini APIs
│   ├── consensus_engine/      # Weighted voting + confidence merging
│   ├── graph_builder/         # Redis graph cache + JSON export
│   ├── orchestrator/          # Document strategy classifier (domain-aware)
│   └── frontend/              # React + D3.js SPA served via Nginx
├── shared/                    # Shared Pydantic models and Redis helpers
├── litellm_config.yaml        # LiteLLM proxy routing config (local dev)
├── docker-compose.yml         # Full local stack (all services separate)
├── .env.example               # Environment variable template
└── README.md
```

---

## 🛡️ License

This project is open-source and available under the **MIT License**.
