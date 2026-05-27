"""
Integration test: upload a document and wait for graph completion.
Run against a live stack: docker compose up -d

Usage:
    python tests/integration/test_pipeline.py
"""
import asyncio
import json
import time
import sys
import httpx

API_BASE = "http://localhost:8000"
SAMPLE_DOC = "docs/sample_document.txt"
TIMEOUT_SECONDS = 300


async def run_test():
    async with httpx.AsyncClient(timeout=60.0) as client:
        # ── 1. Health check ───────────────────────────────────
        print("1. Checking API gateway health...")
        resp = await client.get(f"{API_BASE}/health")
        assert resp.status_code == 200, f"Health check failed: {resp.text}"
        print(f"   ✓ {resp.json()}")

        # ── 2. Upload document ────────────────────────────────
        print(f"2. Uploading {SAMPLE_DOC}...")
        with open(SAMPLE_DOC, "rb") as f:
            resp = await client.post(
                f"{API_BASE}/api/v1/documents/upload",
                files={"file": ("sample_document.txt", f, "text/plain")},
            )
        assert resp.status_code == 200, f"Upload failed: {resp.text}"
        data = resp.json()
        doc_id = data["document_id"]
        print(f"   ✓ Document ID: {doc_id}")

        # ── 3. Poll until completed ───────────────────────────
        print("3. Polling for pipeline completion...")
        start = time.time()
        last_progress = -1
        while time.time() - start < TIMEOUT_SECONDS:
            resp = await client.get(f"{API_BASE}/api/v1/documents/{doc_id}/status")
            state = resp.json()
            progress = state.get("progress_pct", 0)

            if int(progress) != int(last_progress):
                print(f"   [{int(progress):3d}%] {state.get('status')} — "
                      f"chunks={state.get('total_chunks', 0)} "
                      f"agents={state.get('agent_results_received', 0)}")
                last_progress = progress

            if state["status"] == "completed":
                print(f"   ✓ Completed in {time.time()-start:.1f}s")
                break
            elif state["status"] == "failed":
                print(f"   ✗ Failed: {state.get('error_message')}")
                sys.exit(1)
            await asyncio.sleep(2)
        else:
            print(f"   ✗ Timed out after {TIMEOUT_SECONDS}s")
            sys.exit(1)

        # ── 4. Fetch graph ────────────────────────────────────
        print("4. Fetching knowledge graph...")
        resp = await client.get(f"{API_BASE}/api/v1/documents/{doc_id}/graph")
        assert resp.status_code == 200, f"Graph fetch failed: {resp.text}"
        graph = resp.json()

        nodes = graph.get("nodes", [])
        edges = graph.get("edges", [])
        print(f"   ✓ Graph: {len(nodes)} nodes, {len(edges)} edges")

        # ── 5. Assertions ─────────────────────────────────────
        print("5. Running assertions...")
        assert len(nodes) > 0, "No nodes in graph"
        assert len(edges) > 0, "No edges in graph"
        assert graph.get("global_summary"), "No global summary"
        assert graph.get("consensus_method"), "No consensus method"

        # All nodes have required fields
        for node in nodes:
            assert "id" in node, f"Node missing id: {node}"
            assert "label" in node, f"Node missing label: {node}"
            assert 0 <= node.get("confidence", 0) <= 1, f"Invalid confidence: {node}"

        # All edges reference valid nodes
        node_ids = {n["id"] for n in nodes}
        for edge in edges:
            assert edge["source"] in node_ids, f"Dangling edge source: {edge['source']}"
            assert edge["target"] in node_ids, f"Dangling edge target: {edge['target']}"

        print(f"""
   ✓ All assertions passed!
   ✓ Top concepts: {', '.join(n['label'] for n in nodes[:5])}
   ✓ Summary excerpt: {graph['global_summary'][:100]}...
        """)

        # Save output
        with open("docs/test_output.json", "w") as f:
            json.dump(graph, f, indent=2, default=str)
        print("   ✓ Full graph saved to docs/test_output.json")

        print("\n🎉 Integration test PASSED")


if __name__ == "__main__":
    asyncio.run(run_test())
