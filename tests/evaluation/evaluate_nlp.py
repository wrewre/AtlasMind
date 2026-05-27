"""
Evaluation Script — Dimension 1: NLP Output Quality
=====================================================
Compares two graph JSON files (baseline vs agentic) and reports:

  1. ROUGE-L          — label/summary overlap (Recall-oriented F1)
  2. BERTScore F1     — semantic similarity of concept labels
  3. TED Proxy Cost   — structural graph difference (lower is better)
  4. Relation F1      — triplet-level precision/recall/F1
  5. Edge Density     — graph connectivity of the hypothesis output

Usage:
  pip install -r tests/evaluation/requirements.txt
  python tests/evaluation/evaluate_nlp.py --ref baseline.json --hyp agentic.json

How to get the JSON files:
  Option A) From the running service:
    curl http://localhost:8000/api/graph/<document_id> > agentic.json
  Option B) From the Docker volume:
    docker compose cp graph-builder:/app/graphs/<doc_id>.json agentic.json
"""

import json
import sys
import argparse
import os

# ─────────────────────────────────────────────────────────────────────────────
# Lazy imports — give a clean error if deps are missing
# ─────────────────────────────────────────────────────────────────────────────
def _require(pkg):
    import importlib
    try:
        return importlib.import_module(pkg)
    except ImportError:
        print(f"\n[ERROR] Missing package: '{pkg}'. Run:\n  pip install -r tests/evaluation/requirements.txt\n")
        sys.exit(1)


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def load_graph(path: str) -> dict:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def build_nx_graph(data: dict):
    nx = _require("networkx")
    G = nx.DiGraph()
    # Support both key names: the API returns "nodes"/"edges"
    nodes = data.get("nodes") or data.get("concepts") or []
    edges = data.get("edges") or data.get("relationships") or []
    for n in nodes:
        G.add_node(n["id"], label=n.get("label", n["id"]))
    for e in edges:
        G.add_edge(e["source"], e["target"], rel=e.get("relation_type", ""))
    return G


def get_concept_text(data: dict) -> str:
    """Build a single string from all concept labels + global summary."""
    nodes = data.get("nodes") or data.get("concepts") or []
    summary = (data.get("insights", {}) or {}).get("global_summary", "") or data.get("global_summary", "")
    labels = " ".join(n.get("label", n.get("id", "")) for n in nodes)
    return (labels + " " + summary).strip()


def get_triplets(data: dict) -> set:
    edges = data.get("edges") or data.get("relationships") or []
    return {
        (e["source"], e.get("relation_type", "related_to"), e["target"])
        for e in edges
    }


# ─────────────────────────────────────────────────────────────────────────────
# Metric functions
# ─────────────────────────────────────────────────────────────────────────────

def calc_rouge(ref_data, hyp_data) -> dict:
    rouge_scorer = _require("rouge_score.rouge_scorer")
    ref_text = get_concept_text(ref_data)
    hyp_text = get_concept_text(hyp_data)
    if not ref_text or not hyp_text:
        return {"rougeL_f1": 0.0, "rougeL_precision": 0.0, "rougeL_recall": 0.0}
    scorer = rouge_scorer.RougeScorer(["rougeL"], use_stemmer=True)
    s = scorer.score(ref_text, hyp_text)["rougeL"]
    return {"rougeL_f1": s.fmeasure, "rougeL_precision": s.precision, "rougeL_recall": s.recall}


def calc_bertscore(ref_data, hyp_data) -> dict:
    bert_score = _require("bert_score")
    ref_nodes = ref_data.get("nodes") or ref_data.get("concepts") or []
    hyp_nodes = hyp_data.get("nodes") or hyp_data.get("concepts") or []
    ref_text = " ".join(n.get("label", "") for n in ref_nodes)
    hyp_text = " ".join(n.get("label", "") for n in hyp_nodes)
    if not ref_text or not hyp_text:
        return {"bertscore_f1": 0.0, "bertscore_precision": 0.0, "bertscore_recall": 0.0}
    print("  Computing BERTScore (may take 15-30s on first run to download model)...")
    P, R, F1 = bert_score.score(
        [hyp_text], [ref_text],
        lang="en",
        model_type="distilbert-base-uncased",
        verbose=False,
    )
    return {
        "bertscore_f1": F1.mean().item(),
        "bertscore_precision": P.mean().item(),
        "bertscore_recall": R.mean().item(),
    }


def calc_ted(ref_G, hyp_G) -> dict:
    """Proxy for Tree/Graph Edit Distance.
    True GED is NP-Hard; this uses symmetric difference as an O(E) approximation.
    Lower is better — 0 means perfect structural match.
    """
    ref_edges = set(ref_G.edges())
    hyp_edges = set(hyp_G.edges())
    diff_edges = len(ref_edges.symmetric_difference(hyp_edges))
    ref_nodes  = set(ref_G.nodes())
    hyp_nodes  = set(hyp_G.nodes())
    diff_nodes = len(ref_nodes.symmetric_difference(hyp_nodes))
    return {"ted_proxy_cost": diff_edges + diff_nodes}


def calc_relation_f1(ref_data, hyp_data) -> dict:
    ref_triplets = get_triplets(ref_data)
    hyp_triplets = get_triplets(hyp_data)
    if not ref_triplets:
        return {"relation_precision": 0.0, "relation_recall": 0.0, "relation_f1": 0.0}
    tp        = len(ref_triplets & hyp_triplets)
    precision = tp / len(hyp_triplets) if hyp_triplets else 0.0
    recall    = tp / len(ref_triplets)
    f1        = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    return {
        "relation_precision": precision,
        "relation_recall":    recall,
        "relation_f1":        f1,
    }


def calc_edge_density(G) -> dict:
    n = G.number_of_nodes()
    if n <= 1:
        return {"edge_density": 0.0}
    density = G.number_of_edges() / (n * (n - 1))
    return {"edge_density": density}


# ─────────────────────────────────────────────────────────────────────────────
# Main evaluator
# ─────────────────────────────────────────────────────────────────────────────

def evaluate(ref_path: str, hyp_path: str, skip_bert: bool = False):
    print("=" * 55)
    print("  DIMENSION 1 — NLP OUTPUT QUALITY EVALUATION")
    print("=" * 55)
    print(f"  Reference : {ref_path}")
    print(f"  Hypothesis: {hyp_path}")
    print()

    ref_data = load_graph(ref_path)
    hyp_data = load_graph(hyp_path)

    ref_nodes = ref_data.get("nodes") or ref_data.get("concepts") or []
    hyp_nodes = hyp_data.get("nodes") or hyp_data.get("concepts") or []
    ref_edges = ref_data.get("edges") or ref_data.get("relationships") or []
    hyp_edges = hyp_data.get("edges") or hyp_data.get("relationships") or []
    print(f"  Reference : {len(ref_nodes)} nodes, {len(ref_edges)} edges")
    print(f"  Hypothesis: {len(hyp_nodes)} nodes, {len(hyp_edges)} edges")
    print()

    ref_G = build_nx_graph(ref_data)
    hyp_G = build_nx_graph(hyp_data)

    metrics = {}

    print("  [1/5] Computing ROUGE-L...")
    metrics.update(calc_rouge(ref_data, hyp_data))

    if not skip_bert:
        print("  [2/5] Computing BERTScore...")
        metrics.update(calc_bertscore(ref_data, hyp_data))
    else:
        metrics["bertscore_f1"] = "skipped (--no-bert)"

    print("  [3/5] Computing TED Proxy Cost...")
    metrics.update(calc_ted(ref_G, hyp_G))

    print("  [4/5] Computing Relation F1...")
    metrics.update(calc_relation_f1(ref_data, hyp_data))

    print("  [5/5] Computing Edge Density...")
    metrics.update(calc_edge_density(hyp_G))

    print()
    print("=" * 55)
    print("  RESULTS")
    print("=" * 55)
    GOOD_RANGES = {
        "rougeL_f1":         ("↑ higher is better", ">0.30 is good, >0.45 is excellent"),
        "rougeL_precision":  ("↑ higher is better", ""),
        "rougeL_recall":     ("↑ higher is better", ""),
        "bertscore_f1":      ("↑ higher is better", ">0.80 is good"),
        "bertscore_precision":("↑ higher is better", ""),
        "bertscore_recall":  ("↑ higher is better", ""),
        "ted_proxy_cost":    ("↓ lower is better",  "0 = perfect match"),
        "relation_precision":("↑ higher is better", ""),
        "relation_recall":   ("↑ higher is better", ""),
        "relation_f1":       ("↑ higher is better", ">0.30 is good"),
        "edge_density":      ("↑ higher is better", ">0.05 means well-connected"),
    }
    for k, v in metrics.items():
        direction, note = GOOD_RANGES.get(k, ("", ""))
        if isinstance(v, float):
            line = f"  {k:<25} {v:.4f}   {direction}"
        else:
            line = f"  {k:<25} {v}   {direction}"
        if note:
            line += f"  [{note}]"
        print(line)

    print()
    print("  HOW TO INTERPRET:")
    print("  ─────────────────────────────────────────────────")
    print("  ROUGE-L F1  : Did the agentic system capture the same concepts as the baseline?")
    print("                F1 > baseline means IMPROVEMENT in coverage.")
    print("  BERTScore   : Are the extracted concepts semantically equivalent?")
    print("                F1 close to 1.0 means high semantic fidelity.")
    print("  TED Cost    : How different is the graph structure?")
    print("                Cost=0 means identical; lower = more similar.")
    print("  Relation F1 : Are the edges (relationships) correct?")
    print("                Higher F1 = more accurate knowledge connections.")
    print("  Edge Density: How well-connected is the graph?")
    print("                Higher = richer knowledge representation.")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Evaluate NLP Quality of Knowledge Graphs (Dimension 1)"
    )
    parser.add_argument("--ref",     required=True,  help="Reference (baseline) graph JSON")
    parser.add_argument("--hyp",     required=True,  help="Hypothesis (agentic) graph JSON")
    parser.add_argument("--no-bert", action="store_true", help="Skip BERTScore (slow)")
    args = parser.parse_args()
    evaluate(args.ref, args.hyp, skip_bert=args.no_bert)
