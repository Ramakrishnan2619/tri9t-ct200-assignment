"""
End-to-End Demonstration Script for Tri9T AI Internship Assignment
Demonstrates:
  1. Document V1.0 Ingestion & Hierarchy Reconstruction
  2. Section Browsing & Node Detail Retrieval
  3. Version-Pinned Selection Creation
  4. Structured LLM QA Test-Case Generation (Status: CURRENT)
  5. Document V2.0 Re-Ingestion (Detecting modified, unchanged, added nodes)
  6. Dynamic Staleness & Impact Detection (Status: STALE with detailed reasoning)
  7. Verification that Unchanged Sections remain CURRENT
"""

import sys
import os
import time

if sys.stdout.encoding != "utf-8":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass

from fastapi.testclient import TestClient
from app.main import app
from app.store import store
from app.database import init_db

client = TestClient(app)

def print_header(title: str):
    print("\n" + "=" * 75)
    print(f"  {title.upper()}")
    print("=" * 75)

def main():
    print_header("Step 1: Ingesting Baseline CT-200 Manual (Version 1.0)")
    ingest_v1 = client.post("/api/v1/ingest?file_path=data/ct200_manual_v1.pdf&version_label=1.0")
    print(f"Status Code: {ingest_v1.status_code}")
    v1_data = ingest_v1.json()
    v1_id = v1_data["version_id"]
    print(f"Version Ingested: {v1_data['version_label']} (ID: {v1_id})")

    print_header("Step 2: Browsing Top-Level Sections (Version 1.0)")
    sections_resp = client.get("/api/v1/sections?version=1.0")
    sections = sections_resp.json()
    print(f"Found {len(sections)} top-level chapters:")
    for s in sections[:5]:
        print(f"  - [{s['id']}] Level {s['level']}: {s['heading']} (Hash: {s['content_hash'][:8]}...)")

    print_header("Step 3: Searching & Inspecting Section '4.2 Error Codes'")
    search_resp = client.get("/api/v1/nodes?q=Error%20Codes&version=1.0")
    error_nodes = search_resp.json()
    target_node = next(n for n in error_nodes if "4.2" in n["heading"])
    node_id = target_node["id"]
    
    node_detail = client.get(f"/api/v1/nodes/{node_id}").json()
    print(f"Selected Node: {node_detail['heading']}")
    print(f"Path: {node_detail['node_path']}")
    print(f"Content Hash: {node_detail['content_hash']}")
    print(f"Body Text Preview:\n  {node_detail['body_text'][:120]}...")

    print_header("Step 4: Creating Version-Pinned Selection")
    selection_payload = {
        "name": "Safety Fault Ingestion & Error Code QA",
        "version_id": v1_id,
        "node_ids": [node_id]
    }
    sel_resp = client.post("/api/v1/selections", json=selection_payload)
    sel_data = sel_resp.json()
    sel_id = sel_data["id"]
    print(f"Selection Created: '{sel_data['name']}' (ID: {sel_id})")
    print(f"Pinned to Document Version: {sel_data['version_label']}")

    print_header("Step 5: Generating QA Test Cases via LLM")
    gen_resp = client.post("/api/v1/generations", json={"selection_id": sel_id, "force_refresh": True})
    gen_data = gen_resp.json()
    gen_id = gen_data["id"]
    print(f"Generation ID: {gen_id}")
    print(f"Initial Staleness Status: >>> {gen_data['staleness_status']} <<<")
    print(f"Generated {len(gen_data['test_cases'])} Structured QA Test Cases:")
    for i, tc in enumerate(gen_data["test_cases"], 1):
        print(f"\n  [Test Case {i}] {tc['test_title']}")
        print(f"    Prerequisites: {tc['prerequisites']}")
        print(f"    Steps: {tc['steps'][0]} ...")
        print(f"    Expected Result: {tc['expected_result']}")

    print_header("Step 6: Re-Ingesting CT-200 Manual Version 2.0 (Document Update)")
    ingest_v2 = client.post("/api/v1/ingest?file_path=data/ct200_manual_v2.pdf&version_label=2.0")
    v2_data = ingest_v2.json()
    print(f"Re-ingested Version: {v2_data['version_label']} (ID: {v2_data['version_id']})")
    print(f"Active Version Flag: {v2_data['is_active']}")

    print_header("Step 7: Dynamic Staleness & Impact Detection Query")
    retrieval_resp = client.get(f"/api/v1/generations/{gen_id}")
    retrieved = retrieval_resp.json()
    print(f"Generation ID: {retrieved['id']}")
    print(f"Query Time Staleness Status: >>> {retrieved['staleness_status']} <<<")
    print("Detected Staleness / Impact Reasons:")
    for r in retrieved["staleness_reasons"]:
        print(f"  * {r}")

    print_header("Step 8: Verifying Unchanged Section Stability")
    iu_search = client.get("/api/v1/nodes?q=Intended%20Use&version=1.0").json()
    iu_node_id = iu_search[0]["id"]
    iu_sel = client.post("/api/v1/selections", json={
        "name": "Intended Use Baseline",
        "version_id": v1_id,
        "node_ids": [iu_node_id]
    }).json()
    iu_gen = client.post("/api/v1/generations", json={"selection_id": iu_sel["id"]}).json()
    print(f"Section '1.1 Intended Use' Generation Status across V1->V2: >>> {iu_gen['staleness_status']} <<<")
    print(f"Reason: {iu_gen['staleness_reasons'][0]}")

    print_header("Demonstration Workflow Successfully Completed")

if __name__ == "__main__":
    main()
