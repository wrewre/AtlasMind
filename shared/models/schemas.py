"""
Shared Pydantic schemas for inter-service communication.

All services serialize/deserialize messages using these models,
ensuring type safety across service boundaries in the distributed system.
"""
from __future__ import annotations
from enum import Enum
from typing import Any, Dict, List, Optional
from uuid import UUID, uuid4
from datetime import datetime
from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------

class JobStatus(str, Enum):
    PENDING = "pending"
    PROCESSING = "processing"
    COMPLETED = "completed"
    FAILED = "failed"
    RETRYING = "retrying"


class AgentType(str, Enum):
    CONCEPT = "concept"
    RELATIONSHIP = "relationship"
    SUMMARIZATION = "summarization"
    SENTIMENT = "sentiment"


class DocumentType(str, Enum):
    PDF = "pdf"
    TEXT = "text"
    MARKDOWN = "markdown"


# ---------------------------------------------------------------------------
# Document / Ingestion
# ---------------------------------------------------------------------------

class DocumentMetadata(BaseModel):
    filename: str
    file_type: DocumentType
    file_size_bytes: int
    page_count: Optional[int] = None
    language: Optional[str] = "en"
    uploaded_at: datetime = Field(default_factory=datetime.utcnow)


class IngestRequest(BaseModel):
    """Published to 'document.ingested' topic after upload."""
    document_id: UUID = Field(default_factory=uuid4)
    storage_path: str  # path on shared volume / object store
    metadata: DocumentMetadata
    priority: int = Field(default=5, ge=1, le=10)


class ChunkMessage(BaseModel):
    """
    Published to 'chunks.ready' topic.
    Each chunk is an independent unit of work for agents.
    This is the primary fan-out message in the pipeline.
    """
    chunk_id: UUID = Field(default_factory=uuid4)
    document_id: UUID
    chunk_index: int
    total_chunks: int
    text: str
    char_start: int
    char_end: int
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Agent outputs - structured JSON per agent type
# ---------------------------------------------------------------------------

class Concept(BaseModel):
    id: str              # slug, e.g. "machine_learning"
    label: str           # human-readable label
    category: Optional[str] = None
    confidence: float = Field(ge=0.0, le=1.0)
    source_chunk_id: Optional[str] = None


class Relationship(BaseModel):
    source: str          # concept id
    target: str          # concept id
    relation_type: str   # e.g. "is_a", "part_of", "causes", "uses"
    label: str
    confidence: float = Field(ge=0.0, le=1.0)
    source_chunk_id: Optional[str] = None


class AgentOutput(BaseModel):
    """
    Canonical output schema for ALL agents.
    Published to 'agent.results' topic.
    The consensus engine subscribes to this topic.
    """
    agent_id: str
    agent_type: AgentType
    document_id: UUID
    chunk_id: UUID
    chunk_index: int
    total_chunks: int

    # Populated per agent type
    concepts: List[Concept] = Field(default_factory=list)
    relationships: List[Relationship] = Field(default_factory=list)
    summary: Optional[str] = None
    sentiment_score: Optional[float] = None   # -1 to 1
    sentiment_label: Optional[str] = None     # positive / neutral / negative

    confidence_overall: float = Field(default=0.5, ge=0.0, le=1.0)
    processing_time_ms: int = 0
    error: Optional[str] = None
    timestamp: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Consensus / Final graph
# ---------------------------------------------------------------------------

class GraphNode(BaseModel):
    id: str
    label: str
    category: Optional[str] = None
    confidence: float
    mention_count: int = 1
    sentiment: Optional[float] = None
    summary: Optional[str] = None


class GraphEdge(BaseModel):
    source: str
    target: str
    relation_type: str
    label: str
    confidence: float
    weight: float = 1.0


class KnowledgeGraph(BaseModel):
    """
    Final output of the Consensus Engine.
    Stored in Redis and returned to the frontend.
    """
    document_id: UUID
    nodes: List[GraphNode]
    edges: List[GraphEdge]
    global_summary: Optional[str] = None
    total_chunks_processed: int = 0
    consensus_method: str = "weighted_voting"
    generated_at: datetime = Field(default_factory=datetime.utcnow)


# ---------------------------------------------------------------------------
# Job tracking
# ---------------------------------------------------------------------------

class JobState(BaseModel):
    """Stored in Redis for real-time job progress tracking."""
    job_id: UUID
    document_id: UUID
    status: JobStatus = JobStatus.PENDING
    total_chunks: int = 0
    chunks_completed: int = 0
    chunks_failed: int = 0
    agent_results_received: int = 0
    progress_pct: float = 0.0
    error_message: Optional[str] = None
    created_at: datetime = Field(default_factory=datetime.utcnow)
    updated_at: datetime = Field(default_factory=datetime.utcnow)

    def update_progress(self) -> None:
        if self.total_chunks > 0:
            self.progress_pct = round(
                (self.chunks_completed / self.total_chunks) * 100, 1
            )
        self.updated_at = datetime.utcnow()
