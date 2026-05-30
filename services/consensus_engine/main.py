"""
Consensus Engine — with hierarchical tree structure for mind map layout
=======================================================================
Key addition: build_tree_structure() converts the flat concept list into
a topic hierarchy that the frontend renders as a proper radial mind map,
not just floating nodes.
"""
from __future__ import annotations

import asyncio
import json
import os
import re
import time
from datetime import datetime
from collections import defaultdict
from typing import Any, Dict, List, Optional, Tuple

import redis.asyncio as aioredis
import httpx
import structlog

REDIS_URL       = os.getenv("REDIS_URL",    "redis://redis:6379/0")
RESULTS_STREAM  = "agent.results"
GRAPH_STREAM    = "graph.built"
CONSUMER_GROUP  = "consensus-engine"
CONSUMER_NAME   = os.getenv("HOSTNAME",     "consensus-1")

GEMINI_API_KEY  = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY    = os.getenv("GROQ_API_KEY",   "")
GROQ_MODEL      = os.getenv("GROQ_MODEL",     "llama-3.3-70b-versatile")

LITELLM_URL = os.getenv("LITELLM_URL", "http://litellm:4000")
LITELLM_KEY = os.getenv("LITELLM_API_KEY", "sk-mindmap-master-key-2025")

VOTE_THRESHOLD      = int(os.getenv("VOTE_THRESHOLD",      "1"))
CONF_THRESHOLD      = float(os.getenv("CONF_THRESHOLD",    "0.3"))
EDGE_CONF_THRESHOLD = float(os.getenv("EDGE_CONF_THRESHOLD","0.3"))

NUM_AGENTS          = 1      # unified agent: 1 call per chunk
MAX_PROCESSING_WAIT = int(os.getenv("MAX_PROCESSING_WAIT", "300"))

AGENT_WEIGHTS = {
    "unified":       1.0,
    "concept":       1.0,
    "relationship":  0.9,
    "summarization": 0.8,
    "sentiment":     0.7,
}

log = structlog.get_logger("consensus_engine")


# ── Merge concepts ────────────────────────────────────────────────────────────

def merge_concepts(all_concepts: List[Dict], conf_threshold: float = CONF_THRESHOLD) -> List[Dict]:
    groups: Dict[str, List[Dict]] = defaultdict(list)
    for c in all_concepts:
        cid = str(c.get("id", "")).lower().strip()
        if cid:
            groups[cid].append(c)

    merged = []
    for cid, instances in groups.items():
        mention_count  = len(instances)
        if mention_count < VOTE_THRESHOLD:
            continue
        best           = max(instances, key=lambda x: float(x.get("confidence", 0)))
        avg_confidence = sum(float(i.get("confidence", 0)) for i in instances) / mention_count
        if avg_confidence < conf_threshold and mention_count < 2:
            continue
        labels = [i.get("label", cid) for i in instances]
        label  = max(set(labels), key=labels.count)
        sentiments    = [i.get("sentiment") for i in instances if i.get("sentiment") is not None]
        avg_sentiment = sum(sentiments) / len(sentiments) if sentiments else None

        merged.append({
            "id":           cid,
            "label":        label,
            "category":     best.get("category", "CONCEPT"),
            "confidence":   round(min(avg_confidence * (1 + 0.1 * mention_count), 1.0), 3),
            "mention_count":mention_count,
            "sentiment":    round(avg_sentiment, 3) if avg_sentiment is not None else None,
        })

    return sorted(merged, key=lambda x: x["confidence"], reverse=True)


def merge_relationships(all_relationships: List[Dict], valid_ids: set) -> List[Dict]:
    groups: Dict[Tuple, List[Dict]] = defaultdict(list)
    for r in all_relationships:
        src = str(r.get("source", "")).lower().strip()
        tgt = str(r.get("target", "")).lower().strip()
        rel = str(r.get("relation_type", "related_to"))
        if src and tgt and src != tgt:
            groups[(src, tgt, rel)].append(r)

    merged    = []
    seen_pairs: set = set()

    for (src, tgt, rel), instances in groups.items():
        if src not in valid_ids or tgt not in valid_ids:
            continue
        if (tgt, src) in seen_pairs:
            continue
        avg_conf = sum(float(i.get("confidence", 0.5)) for i in instances) / len(instances)
        if avg_conf < EDGE_CONF_THRESHOLD:
            continue
        best   = max(instances, key=lambda x: float(x.get("confidence", 0)))
        weight = min(avg_conf * len(instances), 1.0)
        merged.append({
            "source":        src,
            "target":        tgt,
            "relation_type": rel,
            "label":         best.get("label", rel.replace("_", " ")),
            "confidence":    round(avg_conf, 3),
            "weight":        round(weight, 3),
        })
        seen_pairs.add((src, tgt))

    return merged


# ── Hierarchical tree structure (for mind map radial layout) ─────────────────

def build_tree_structure(nodes: List[Dict], edges: List[Dict]) -> Dict:
    """
    Convert flat graph into hierarchical topic tree for mind map rendering.

    This is the key difference from a generic force-directed graph:
    - Identifies the highest-importance concepts as main branches
    - Uses 'is_a', 'part_of', 'enables', 'implements' edges to determine parent-child
    - Groups remaining concepts into category clusters (Technology, Person, etc.)
    - Produces a radial tree structure the frontend can render like NotebookLM

    The resulting tree is stored alongside the flat nodes/edges so the frontend
    can switch between 'mind map' view (radial tree) and 'graph' view (force-directed).
    """
    if not nodes:
        return {"id": "root", "label": "Document", "children": [], "category": "ROOT"}

    # Edges that imply parent→child hierarchy
    hierarchy_rels = {"is_a", "part_of", "enables", "implements"}
    children_map: Dict[str, List[str]] = {n["id"]: [] for n in nodes}
    parent_map:   Dict[str, str]       = {}

    for edge in edges:
        src = edge["source"]
        tgt = edge["target"]
        rel = edge["relation_type"]
        # "A is_a B" → A is child of B (B is more general/central)
        if rel in hierarchy_rels:
            if tgt in children_map and src not in parent_map:
                children_map.setdefault(tgt, []).append(src)
                parent_map[src] = tgt
        # "A uses B" / "A requires B" → A and B are siblings under a common parent
        # (don't create parent-child, but record co-occurrence for clustering)

    # Identify root nodes: high-confidence concepts with no parent
    root_candidates = [n for n in nodes if n["id"] not in parent_map]
    if not root_candidates:
        root_candidates = sorted(nodes, key=lambda n: n["confidence"], reverse=True)

    # Sort roots by (confidence × mention_count) — most important first
    root_candidates = sorted(
        root_candidates,
        key=lambda n: n["confidence"] * n.get("mention_count", 1),
        reverse=True
    )

    # Take top 6 roots as main mind map branches (fewer = more angular space)
    main_roots = root_candidates[:6]
    main_root_ids = {r["id"] for r in main_roots}

    def make_node(n: Dict, depth: int = 0, visited: set = None) -> Dict:
        if visited is None:
            visited = set()
        node_id = n["id"]
        if node_id in visited or depth > 3:
            return {"id": node_id, "label": n["label"],
                    "category": n.get("category","CONCEPT"),
                    "confidence": n.get("confidence",0.5),
                    "mention_count": n.get("mention_count",1),
                    "sentiment": n.get("sentiment"),
                    "children": []}
        visited = visited | {node_id}

        child_ids   = [cid for cid in children_map.get(node_id, []) if cid != node_id]
        child_nodes = [next((x for x in nodes if x["id"] == cid), None) for cid in child_ids]
        child_nodes = [c for c in child_nodes if c is not None][:5]  # max 5 children per node

        return {
            "id":           node_id,
            "label":        n["label"],
            "category":     n.get("category", "CONCEPT"),
            "confidence":   n.get("confidence", 0.5),
            "mention_count":n.get("mention_count", 1),
            "sentiment":    n.get("sentiment"),
            "children":     [make_node(c, depth+1, visited) for c in child_nodes],
        }

    # Build main branch nodes
    tree_children = [make_node(n) for n in main_roots]

    # Collect concepts not yet in any branch
    all_placed = set()
    def collect_ids(node):
        all_placed.add(node["id"])
        for c in node.get("children", []):
            collect_ids(c)
    for t in tree_children:
        collect_ids(t)

    unplaced = [n for n in nodes if n["id"] not in all_placed]

    # Group unplaced by category and attach as category cluster branches
    category_clusters: Dict[str, List[Dict]] = {}
    for n in unplaced:
        cat = n.get("category", "CONCEPT")
        category_clusters.setdefault(cat, []).append(n)

    for cat, cat_nodes in category_clusters.items():
        if not cat_nodes:
            continue
        # Only make a cluster if there are 2+ concepts in the same category
        if len(cat_nodes) >= 2:
            cluster = {
                "id":           f"cluster_{cat.lower()}",
                "label":        cat.replace("_", " ").title(),
                "category":     "CLUSTER",
                "confidence":   0.75,
                "mention_count":len(cat_nodes),
                "sentiment":    None,
                "children":     [make_node(n) for n in cat_nodes[:5]],
            }
            tree_children.append(cluster)
        else:
            # Single unplaced concept — attach to the nearest main root
            if tree_children:
                tree_children[0]["children"].append(make_node(cat_nodes[0]))

    return {
        "id":           "document_root",
        "label":        "Document",
        "category":     "ROOT",
        "confidence":   1.0,
        "mention_count":len(nodes),
        "sentiment":    None,
        "children":     tree_children,
    }


# ── Conflict detection ────────────────────────────────────────────────────────

def detect_conflicts(edges: List[Dict]) -> List[Dict]:
    """
    Find contradictory relationships in the knowledge graph.
    Examples: A causes B AND B causes A = circular causation (flagged)
              A is_a B AND B is_a A = contradictory taxonomy
    
    Returns list of conflict records shown as red edges in the UI.
    This is a novelty feature — NotebookLM does NOT do this.
    """
    conflicts = []
    edge_index = {}
    for e in edges:
        key = (e["source"], e["target"], e["relation_type"])
        edge_index[key] = e

    contradictory_pairs = [
        ("causes",  "causes"),       # A→B and B→A both cause each other
        ("is_a",    "is_a"),         # A is_a B and B is_a A
        ("enables", "requires"),     # A enables B and B requires A (circular dependency)
    ]

    for e in edges:
        src, tgt, rel = e["source"], e["target"], e["relation_type"]
        for rel1, rel2 in contradictory_pairs:
            if rel == rel1:
                reverse_key = (tgt, src, rel2)
                if reverse_key in edge_index:
                    conflicts.append({
                        "type":        "contradiction",
                        "edge_a":      {"source": src, "target": tgt, "relation": rel},
                        "edge_b":      {"source": tgt, "target": src, "relation": rel2},
                        "description": f"Contradictory: {src} {rel} {tgt} AND {tgt} {rel2} {src}",
                    })
    return conflicts


# ── Global summary synthesis ──────────────────────────────────────────────────

async def call_llm(system: str, user: str, max_tokens: int = 800, temperature: float = 0.1) -> str:
    """Call LLM, trying LiteLLM first, falling back to Groq -> Gemini -> OpenRouter -> Ollama direct calls."""
    gemini_key = os.getenv("GEMINI_API_KEY")
    groq_key = os.getenv("GROQ_API_KEY")
    openrouter_key = os.getenv("OPENROUTER_API_KEY")
    
    use_direct_fallback = False
    if gemini_key or groq_key or openrouter_key:
        if os.getenv("LITELLM_URL") is None or "litellm:4000" in LITELLM_URL:
            use_direct_fallback = True

    if not use_direct_fallback:
        # Try LiteLLM proxy
        try:
            async with httpx.AsyncClient(timeout=45.0) as http:
                resp = await http.post(
                    f"{LITELLM_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                    json={
                        "model": "summary",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user}
                        ],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            log.warning("litellm_call_failed", error=str(exc))

    # Direct fallback cascade if LiteLLM is not running or failed
    errors = []
    
    # 1. Groq Direct
    if groq_key:
        try:
            keys = [
                groq_key,
                os.getenv("GROQ_API_KEY_2"),
                os.getenv("GROQ_API_KEY_3"),
                os.getenv("GROQ_API_KEY_4"),
            ]
            active_keys = [k for k in keys if k]
            for key in active_keys:
                try:
                    async with httpx.AsyncClient(timeout=30.0) as http:
                        resp = await http.post(
                            "https://api.groq.com/openai/v1/chat/completions",
                            headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json"},
                            json={
                                "model": "llama-3.3-70b-versatile",
                                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
                                "max_tokens": max_tokens,
                                "temperature": temperature,
                            },
                        )
                        if resp.status_code == 200:
                            return resp.json()["choices"][0]["message"]["content"].strip()
                        else:
                            resp.raise_for_status()
                except Exception as exc:
                    log.warning("groq_key_failed_trying_next", error=str(exc))
                    continue
        except Exception as exc:
            errors.append(f"Groq: {exc}")

    # 2. Gemini Direct
    if gemini_key:
        try:
            url = f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={gemini_key}"
            payload = {
                "contents": [{"role": "user", "parts": [{"text": user}]}],
                "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}
            }
            if system:
                payload["systemInstruction"] = {"parts": [{"text": system}]}
            
            async with httpx.AsyncClient(timeout=60.0) as http:
                resp = await http.post(url, headers={"Content-Type": "application/json"}, json=payload)
                resp.raise_for_status()
                data = resp.json()
                return data["candidates"][0]["content"]["parts"][0]["text"].strip()
        except Exception as exc:
            errors.append(f"Gemini: {exc}")
            log.warning("direct_gemini_failed_trying_openrouter", error=str(exc))

    # 3. OpenRouter Direct
    if openrouter_key:
        try:
            async with httpx.AsyncClient(timeout=45.0) as http:
                resp = await http.post(
                    "https://openrouter.ai/api/v1/chat/completions",
                    headers={
                        "Authorization": f"Bearer {openrouter_key}",
                        "Content-Type": "application/json",
                        "HTTP-Referer": "https://github.com/wrewre/AtlasMind",
                        "X-Title": "AtlasMind",
                    },
                    json={
                        "model": "openrouter/free",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user},
                        ],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            errors.append(f"OpenRouter: {exc}")
            log.warning("direct_openrouter_failed_trying_ollama", error=str(exc))

    # 4. Ollama Direct
    ollama_host = os.getenv("OLLAMA_HOST")
    if ollama_host and "ollama:11434" not in ollama_host:
        try:
            ollama_model = os.getenv("OLLAMA_MODEL", "llama3.2")
            async with httpx.AsyncClient(timeout=120.0) as http:
                resp = await http.post(
                    f"{ollama_host}/api/generate",
                    json={
                        "model": ollama_model,
                        "system": system,
                        "prompt": user,
                        "stream": False,
                        "options": {
                            "temperature": temperature,
                            "num_predict": max_tokens,
                        }
                    },
                )
                resp.raise_for_status()
                data = resp.json()
                return data.get("response", "").strip()
        except Exception as exc:
            errors.append(f"Ollama: {exc}")
            log.error("direct_ollama_failed", error=str(exc))

    # Fallback to LiteLLM if we bypassed it initially but direct calls failed
    if use_direct_fallback:
        try:
            async with httpx.AsyncClient(timeout=45.0) as http:
                resp = await http.post(
                    f"{LITELLM_URL}/v1/chat/completions",
                    headers={"Authorization": f"Bearer {LITELLM_KEY}"},
                    json={
                        "model": "summary",
                        "messages": [
                            {"role": "system", "content": system},
                            {"role": "user",   "content": user}
                        ],
                        "max_tokens": max_tokens,
                        "temperature": temperature,
                    },
                )
                if resp.status_code == 200:
                    return resp.json()["choices"][0]["message"]["content"].strip()
        except Exception as exc:
            errors.append(f"LiteLLM Fallback: {exc}")

    raise RuntimeError(f"All LLM providers failed: {'; '.join(errors)}")


async def synthesize_global_summary(chunk_summaries: List[Tuple[int, str]]) -> str:
    if not chunk_summaries:
        return ""
    ordered  = sorted(chunk_summaries, key=lambda x: x[0])
    combined = "\n".join(f"[Section {i+1}]: {s}" for i, (_, s) in enumerate(ordered))
    if len(combined) > 5000:
        combined = combined[:5000] + "..."

    system = "Synthesise section summaries into a coherent overall document summary. Write 3-5 sentences."
    user   = f"Synthesise these section summaries:\n\n{combined}"

    try:
        return await call_llm(system, user, max_tokens=400, temperature=0.1)
    except Exception as exc:
        log.warning("global_summary_failed", error=str(exc))

    return " ".join(s for _, s in ordered[:3])


# ── NotebookLM-style RAG Insights ────────────────────────────────────────────

async def synthesize_rag_insights(
    chunk_summaries: List[Tuple[int, str]],
    merged_concepts: List[Dict],
    global_summary: str,
) -> Dict:
    """
    Generates three things alongside the existing keyword graph (untouched):
      1. Rich narrative global summary (2-3 paragraphs, NotebookLM-style)
      2. Key themes  — extracted from top concepts, NO extra LLM call
      3. Per-concept descriptions — top 15 concepts batched into 1 LLM call

    Uses the call_llm helper for automatic direct Gemini fallback.
    """
    if not chunk_summaries:
        return {"global_summary": global_summary, "themes": [], "concept_descriptions": {}}

    ordered  = sorted(chunk_summaries, key=lambda x: x[0])
    combined = "\n\n".join(
        f"[Section {i+1} of {len(ordered)}]: {s}"
        for i, (_, s) in enumerate(ordered)
    )
    if len(combined) > 6000:
        combined = combined[:6000] + "..."

    # ── 1. Rich narrative (1 LLM call) ──────────────────────────────────────
    narrative_system = (
        "You are a document analyst. Given section summaries, write a deep analytical "
        "overview in 2-3 paragraphs covering: the main thesis or central argument, "
        "key actors/technologies/concepts involved, how sections relate and build toward "
        "the overall message, and key takeaways. Write flowing analytical prose — "
        "no bullet points, no headers, no section number references."
    )
    narrative_user = f"Analyse these section summaries and write a deep document overview:\n\n{combined}"
    narrative = ""

    try:
        narrative = await call_llm(narrative_system, narrative_user, max_tokens=800, temperature=0.2)
    except Exception as exc:
        log.warning("insights_narrative_failed", error=str(exc))

    # Fallback: use the existing short global summary
    if not narrative:
        narrative = global_summary

    # ── 2. Key themes — extracted from top concepts, zero extra LLM calls ───
    top_concepts = sorted(
        merged_concepts,
        key=lambda c: c.get("confidence", 0) * c.get("mention_count", 1),
        reverse=True,
    )
    themes = [c["label"] for c in top_concepts[:8] if c.get("label")]

    # ── 3. Per-concept descriptions (1 batched LLM call) ────────────────────
    top_15 = top_concepts[:15]
    concept_descriptions: Dict[str, str] = {}

    if top_15:
        concept_list_str = "\n".join(
            f'  - id: "{c["id"]}" | label: "{c.get("label", c["id"])}" | category: {c.get("category", "CONCEPT")}'
            for c in top_15
        )
        concepts_system = (
            "You are a document analyst. For each concept listed, write exactly 1-2 sentences "
            "explaining what it means IN THE CONTEXT OF THIS SPECIFIC DOCUMENT (not a general definition). "
            'Respond ONLY with a valid JSON object: {"concept_id": "description", ...}'
        )
        concepts_user = (
            f"Document overview: {narrative[:600]}\n\n"
            f"Concepts to describe:\n{concept_list_str}\n\n"
            "Return ONLY a JSON object mapping each concept id to a 1-2 sentence description "
            "of its specific role in this document."
        )

        raw_json = ""
        try:
            raw_json = await call_llm(concepts_system, concepts_user, max_tokens=1200, temperature=0.1)
        except Exception as exc:
            log.warning("insights_concepts_failed", error=str(exc))

        if raw_json:
            clean = re.sub(r"^```(?:json)?\s*", "", raw_json.strip())
            clean = re.sub(r"\s*```\s*$",       "", clean.strip())
            for parser in [
                lambda s: json.loads(s),
                lambda s: json.loads(re.search(r'\{.*\}', s, re.DOTALL).group()),
            ]:
                try:
                    concept_descriptions = parser(clean)
                    break
                except Exception:
                    pass

    log.info("insights_ready",
             narrative_len=len(narrative),
             themes=len(themes),
             concept_descriptions=len(concept_descriptions))

    return {
        "global_summary":       narrative,
        "themes":               themes,
        "concept_descriptions": concept_descriptions,
    }


# ── Main graph builder ────────────────────────────────────────────────────────

async def build_graph(redis_client: aioredis.Redis, document_id: str) -> Dict:
    raw_list = await redis_client.lrange(f"agent:results:{document_id}", 0, -1)
    results  = []
    for item in raw_list:
        try:
            results.append(json.loads(item))
        except Exception:
            pass

    state_raw    = await redis_client.get(f"job:state:{document_id}")
    state        = json.loads(state_raw) if state_raw else {}
    total_chunks = state.get("total_chunks", 0)

    all_concepts:      List[Dict]           = []
    all_relationships: List[Dict]           = []
    chunk_summaries:   List[Tuple[int,str]] = []
    concept_sentiments_map: Dict[str, List[float]] = defaultdict(list)

    for r in results:
        if r.get("failed"):
            continue
        agent_type = r.get("agent_type", "unified")
        weight     = AGENT_WEIGHTS.get(agent_type, 0.8)

        for c in r.get("concepts", []):
            cc = dict(c)
            cc["confidence"] = float(cc.get("confidence", 0.5)) * weight
            all_concepts.append(cc)

        for rel in r.get("relationships", []):
            rr = dict(rel)
            rr["confidence"] = float(rr.get("confidence", 0.5)) * weight
            all_relationships.append(rr)

        if r.get("summary"):
            chunk_summaries.append((int(r.get("chunk_index", 0)), r["summary"]))

        for cs in r.get("concept_sentiments", []):
            cid = cs.get("concept_id", "")
            if cid:
                concept_sentiments_map[cid].append(float(cs.get("sentiment", 0.0)))

    # Apply sentiment
    for c in all_concepts:
        cid = c.get("id", "")
        if cid in concept_sentiments_map:
            c["sentiment"] = sum(concept_sentiments_map[cid]) / len(concept_sentiments_map[cid])

    # Adaptive threshold — keep loosening until we have concepts
    merged_concepts: List[Dict] = []
    for threshold in [CONF_THRESHOLD, 0.25, 0.15, 0.05]:
        merged_concepts = merge_concepts(all_concepts, conf_threshold=threshold)
        if len(merged_concepts) >= 3:
            break

    valid_ids           = {c["id"] for c in merged_concepts}
    merged_relationships = merge_relationships(all_relationships, valid_ids)
    global_summary       = await synthesize_global_summary(chunk_summaries)

    # Build hierarchical tree for mind map view
    tree_structure = build_tree_structure(merged_concepts, merged_relationships)

    # Detect conflicts
    conflicts = detect_conflicts(merged_relationships)

    # NotebookLM-style RAG insights (runs after graph is built, same API cascade)
    insights = await synthesize_rag_insights(chunk_summaries, merged_concepts, global_summary)

    # ── Aggregate agentic metrics across all chunk results ────────────────────
    llm_usage: Dict[str, int] = defaultdict(int)
    strategy_usage: Dict[str, int] = defaultdict(int)
    total_react_iterations   = 0
    total_critic_filtered    = 0
    total_processing_ms      = 0
    react_retry_count        = 0
    valid_results            = [r for r in results if not r.get("failed")]

    for r in valid_results:
        llm      = r.get("llm_used", "unknown")
        strategy = r.get("extraction_strategy", "balanced")
        llm_usage[llm]           += 1
        strategy_usage[strategy] += 1
        total_react_iterations   += int(r.get("react_iterations", 1))
        total_critic_filtered    += int(r.get("critic_filtered_count", 0))
        total_processing_ms      += int(r.get("processing_time_ms", 0))
        if int(r.get("react_iterations", 1)) > 1:
            react_retry_count += 1

    n = max(len(valid_results), 1)
    agentic_metrics = {
        "llm_usage":                dict(llm_usage),       # {"gemini": 8, "groq": 3, "ollama": 1}
        "strategy_usage":           dict(strategy_usage),  # {"relationship_first": 7, "balanced": 5}
        "avg_react_iterations":     round(total_react_iterations / n, 2),
        "react_retry_count":        react_retry_count,     # chunks that needed a second attempt
        "total_critic_filtered":    total_critic_filtered, # relationships removed by critic
        "avg_processing_ms":        int(total_processing_ms / n),
        "fallback_rate_pct":        round(
            (llm_usage.get("groq", 0) + llm_usage.get("ollama", 0)) / max(sum(llm_usage.values()), 1) * 100, 1
        ),
        "domain":                   state.get("orchestrator", {}).get("domain", "general"),
        "orchestrator_strategy":    state.get("orchestrator", {}).get("strategy", "balanced"),
        "orchestrator_decided_by":  state.get("orchestrator", {}).get("decided_by", "unknown"),
    }

    return {
        "document_id":            document_id,
        "nodes":                  merged_concepts,
        "edges":                  merged_relationships,
        "tree":                   tree_structure,
        "conflicts":              conflicts,
        "global_summary":         global_summary,
        "insights":               insights,
        "total_chunks_processed": total_chunks,
        "consensus_method":       "weighted_voting_confidence_merging",
        "agentic_metrics":        agentic_metrics,
        "stats": {
            "total_agent_results":        len(results),
            "failed_agent_results":       sum(1 for r in results if r.get("failed")),
            "concepts_before_merge":      len(all_concepts),
            "concepts_after_merge":       len(merged_concepts),
            "relationships_before_merge": len(all_relationships),
            "relationships_after_merge":  len(merged_relationships),
            "conflicts_detected":         len(conflicts),
        },
    }


# ── Result accumulation and trigger ──────────────────────────────────────────

async def process_agent_result(redis_client: aioredis.Redis, data: dict):
    document_id = data.get("document_id", "")
    if not document_id:
        return
    try:
        payload = json.loads(data.get("payload", "{}"))
    except Exception:
        payload = {}

    await redis_client.rpush(f"agent:results:{document_id}", json.dumps(payload, default=str))
    await redis_client.expire(f"agent:results:{document_id}", 86400)

    state_raw = await redis_client.get(f"job:state:{document_id}")
    if not state_raw:
        return

    state    = json.loads(state_raw)
    received = state.get("agent_results_received", 0) + 1
    state["agent_results_received"] = received

    total_chunks = state.get("total_chunks", 0)
    expected     = total_chunks * NUM_AGENTS if total_chunks > 0 else 1
    state["progress_pct"] = round(min(received / expected * 90, 90), 1)
    state["status"]       = "processing"
    await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))

    total_chunks_data = int(data.get("total_chunks", 0))
    if total_chunks_data > 0 and received >= total_chunks_data * NUM_AGENTS:
        await trigger_consensus(redis_client, document_id, state)


async def trigger_consensus(redis_client: aioredis.Redis, document_id: str, state: dict):
    lock_key = f"lock:consensus:{document_id}"
    locked   = await redis_client.set(lock_key, "1", nx=True, ex=300)
    if not locked:
        return
    try:
        log.info("triggering_consensus", document_id=document_id)
        graph = await build_graph(redis_client, document_id)
        
        # ── Compute System Performance Metrics (Dimension 2) ──
        ingestion_start = state.get("ingestion_start")
        completion_time = datetime.now().isoformat()
        latency = 0
        if ingestion_start:
            start = datetime.fromisoformat(ingestion_start)
            end = datetime.fromisoformat(completion_time)
            latency = (end - start).total_seconds()
            
        metrics = {
            "ingestion_start": ingestion_start,
            "graph_completion": completion_time,
            "latency_seconds": round(latency, 2),
            "total_chunks": state.get("total_chunks", 0),
            "processed_chunks": state.get("agent_results_received", 0),
            "chunk_coverage": round((state.get("agent_results_received", 0) / max(state.get("total_chunks", 1), 1)) * 100, 1),
            "worker_nodes_est": os.getenv("HOSTNAME", "unknown") # hostname of consensus
        }
        graph["performance_metrics"] = metrics

        await redis_client.setex(f"graph:{document_id}", 86400*7, json.dumps(graph, default=str))
        state["status"]       = "completed"
        state["progress_pct"] = 100.0
        await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))
        await redis_client.publish(
            f"updates:{document_id}",
            json.dumps({"event":"graph_ready","document_id":document_id,"progress":100})
        )
        await redis_client.xadd(GRAPH_STREAM, {
            "document_id": document_id,
            "node_count":  str(len(graph["nodes"])),
            "edge_count":  str(len(graph["edges"])),
            "latency":     str(round(latency, 2))
        })
        log.info("consensus_complete", document_id=document_id,
                 nodes=len(graph["nodes"]), edges=len(graph["edges"]),
                 conflicts=len(graph.get("conflicts",[])))
    except Exception as exc:
        log.error("consensus_failed", document_id=document_id, error=str(exc))
        state["status"]        = "failed"
        state["error_message"] = str(exc)
        await redis_client.setex(f"job:state:{document_id}", 86400, json.dumps(state))
    finally:
        await redis_client.delete(lock_key)


# ── Timeout watchdog ──────────────────────────────────────────────────────────

async def timeout_watchdog(redis_client: aioredis.Redis):
    log.info("timeout_watchdog_started", max_wait=MAX_PROCESSING_WAIT)
    while True:
        await asyncio.sleep(30)
        try:
            keys = await redis_client.keys("job:state:*")
            now  = time.time()
            for key in keys:
                raw = await redis_client.get(key)
                if not raw:
                    continue
                state = json.loads(raw)
                if state.get("status") != "processing":
                    continue
                doc_id   = key.replace("job:state:", "")
                received = state.get("agent_results_received", 0)
                total_chunks = state.get("total_chunks", 0)
                wait_key = f"watchdog:last_count:{doc_id}"
                last_raw = await redis_client.get(wait_key)
                if last_raw:
                    last_data  = json.loads(last_raw)
                    last_recv  = last_data.get("received", 0)
                    last_time  = last_data.get("time", now)
                    stale_secs = now - last_time
                    if received == last_recv and stale_secs > MAX_PROCESSING_WAIT:
                        if received >= max(total_chunks, 1):
                            log.warning("watchdog_forcing_consensus",
                                        doc_id=doc_id, received=received,
                                        stale_secs=int(stale_secs))
                            await trigger_consensus(redis_client, doc_id, state)
                            await redis_client.delete(wait_key)
                            continue
                await redis_client.setex(wait_key, MAX_PROCESSING_WAIT+60,
                                         json.dumps({"received": received, "time": now}))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("watchdog_error", error=str(exc))


# ── Consumer loop ─────────────────────────────────────────────────────────────

async def run_consumer():
    redis_client = aioredis.from_url(REDIS_URL, decode_responses=True)
    try:
        await redis_client.xgroup_create(RESULTS_STREAM, CONSUMER_GROUP, id="0", mkstream=True)
    except aioredis.ResponseError as e:
        if "BUSYGROUP" not in str(e):
            raise

    log.info("consensus_engine_ready", consumer=CONSUMER_NAME)
    asyncio.create_task(timeout_watchdog(redis_client))

    while True:
        try:
            messages = await redis_client.xreadgroup(
                CONSUMER_GROUP, CONSUMER_NAME,
                {RESULTS_STREAM: ">"},
                count=20, block=2000,
            )
            if not messages:
                continue
            for stream, entries in messages:
                for msg_id, data in entries:
                    try:
                        await process_agent_result(redis_client, data)
                        await redis_client.xack(RESULTS_STREAM, CONSUMER_GROUP, msg_id)
                    except Exception as exc:
                        log.error("result_processing_error", msg_id=msg_id, error=str(exc))
        except asyncio.CancelledError:
            break
        except Exception as exc:
            log.error("consumer_loop_error", error=str(exc))
            await asyncio.sleep(2)

    await redis_client.aclose()


if __name__ == "__main__":
    asyncio.run(run_consumer())
