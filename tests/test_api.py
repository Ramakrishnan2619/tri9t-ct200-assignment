import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.main import app
from app.store import store
from app.ingest import ingest_document_version
from app.models import DocumentVersion, Node

# Set up dedicated test database
TEST_DB_PATH = "./test_api.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_PATH}"

test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db

@pytest.fixture(scope="module", autouse=True)
def setup_test_environment():
    # Remove old test DB and store if existing
    if os.path.exists(TEST_DB_PATH):
        os.remove(TEST_DB_PATH)
    store.clear()
    
    Base.metadata.create_all(bind=test_engine)
    db = TestingSessionLocal()
    
    # Ingest baseline v1
    v1 = ingest_document_version("data/ct200_manual_v1.pdf", "1.0", db=db)
    db.close()
    
    yield
    
    # Teardown
    if os.path.exists(TEST_DB_PATH):
        try:
            os.remove(TEST_DB_PATH)
        except Exception:
            pass
    store.clear()

@pytest.fixture
def client():
    return TestClient(app)

def test_browse_sections_endpoint(client):
    """GET /api/v1/sections should return all Level 1 top-level chapters."""
    resp = client.get("/api/v1/sections?version=1.0")
    assert resp.status_code == 200
    sections = resp.json()
    assert len(sections) >= 8
    headings = [s["heading"] for s in sections]
    assert any("Device Overview" in h for h in headings)
    assert any("Alarms and Safety Behavior" in h for h in headings)
    assert any("Regulatory Information" in h for h in headings)

def test_search_nodes_endpoint(client):
    """GET /api/v1/nodes?q=overpressure should find safety nodes."""
    resp = client.get("/api/v1/nodes?q=overpressure&version=1.0")
    assert resp.status_code == 200
    results = resp.json()
    assert len(results) >= 1
    assert any("Overpressure Protection" in r["heading"] for r in results)

def test_node_details_and_diff_endpoint(client):
    """GET /api/v1/nodes/{id} and /diff should return full details and diff summary."""
    # Find Section 4.1 node ID
    search_resp = client.get("/api/v1/nodes?q=Overpressure&version=1.0")
    node_id = search_resp.json()[0]["id"]

    detail_resp = client.get(f"/api/v1/nodes/{node_id}")
    assert detail_resp.status_code == 200
    detail = detail_resp.json()
    assert "content_hash" in detail
    assert "body_text" in detail
    assert len(detail["content_hash"]) == 64

    diff_resp = client.get(f"/api/v1/nodes/{node_id}/diff")
    assert diff_resp.status_code == 200
    diff = diff_resp.json()
    assert "has_changed" in diff

def test_version_pinned_selection_and_generation_flow(client):
    """
    End-to-end test of:
    1. Creating a selection on Section 4.2 Error Codes in v1.
    2. Generating QA test cases via LLM.
    3. Validating idempotency on re-submission.
    4. Re-ingesting v2 (where 4.2 Error Codes modified with E6 and deflation time).
    5. Retrieving generation and confirming staleness dynamically flips to STALE.
    """
    db = TestingSessionLocal()
    v1_ver = db.query(DocumentVersion).filter(DocumentVersion.version_label == "1.0").first()
    
    # 1. Locate Error Codes node in v1
    err_node = db.query(Node).filter(
        Node.version_id == v1_ver.id,
        Node.heading.like("%4.2 Error Codes%")
    ).first()
    assert err_node is not None
    db.close()

    # Create Selection
    sel_payload = {
        "name": "Safety Error Codes Test Suite",
        "version_id": v1_ver.id,
        "node_ids": [err_node.id]
    }
    sel_resp = client.post("/api/v1/selections", json=sel_payload)
    assert sel_resp.status_code == 201
    selection = sel_resp.json()
    sel_id = selection["id"]

    # 2. Generate QA test cases
    gen_payload = {"selection_id": sel_id, "force_refresh": False}
    gen_resp = client.post("/api/v1/generations", json=gen_payload)
    assert gen_resp.status_code == 201
    gen_data = gen_resp.json()
    gen_id = gen_data["id"]

    # Assert structured test cases
    assert len(gen_data["test_cases"]) >= 1
    assert gen_data["staleness_status"] == "CURRENT"
    first_tc = gen_data["test_cases"][0]
    assert "test_title" in first_tc
    assert "steps" in first_tc
    assert "expected_result" in first_tc

    # 3. Test idempotency policy: repeated call without force_refresh returns cached record
    gen_resp_2 = client.post("/api/v1/generations", json=gen_payload)
    assert gen_resp_2.status_code == 201
    assert gen_resp_2.json()["id"] == gen_id
    assert gen_resp_2.json()["is_cached"] is True

    # 4. Trigger re-ingestion of v2 manual
    ingest_resp = client.post("/api/v1/ingest?file_path=data/ct200_manual_v2.pdf&version_label=2.0")
    assert ingest_resp.status_code == 201

    # 5. Fetch generation by ID: should now dynamically evaluate to STALE!
    retrieval_resp = client.get(f"/api/v1/generations/{gen_id}")
    assert retrieval_resp.status_code == 200
    retrieved = retrieval_resp.json()
    assert retrieved["staleness_status"] == "STALE"
    assert len(retrieved["staleness_reasons"]) > 0
    assert any("modified" in r.lower() for r in retrieved["staleness_reasons"])

    # 6. Verify retrieval by selection_id
    by_sel_resp = client.get(f"/api/v1/generations/by-selection/{sel_id}")
    assert by_sel_resp.status_code == 200
    assert len(by_sel_resp.json()) >= 1
    assert by_sel_resp.json()[0]["id"] == gen_id

    # 7. Verify retrieval by node_id
    by_node_resp = client.get(f"/api/v1/generations/by-node/{err_node.id}")
    assert by_node_resp.status_code == 200
    assert len(by_node_resp.json()) >= 1
    assert by_node_resp.json()[0]["id"] == gen_id

def test_unchanged_section_remains_current_across_versions(client):
    """
    Asserts that if a selection was created on an unchanged node (e.g. 1.1 Intended Use),
    its generated test cases remain CURRENT even after v2 is ingested.
    """
    db = TestingSessionLocal()
    v1_ver = db.query(DocumentVersion).filter(DocumentVersion.version_label == "1.0").first()
    iu_node = db.query(Node).filter(
        Node.version_id == v1_ver.id,
        Node.heading.like("%1.1 Intended Use%")
    ).first()
    assert iu_node is not None
    db.close()

    # Create selection on unchanged node
    sel_resp = client.post("/api/v1/selections", json={
        "name": "Intended Use Verification",
        "version_id": v1_ver.id,
        "node_ids": [iu_node.id]
    })
    sel_id = sel_resp.json()["id"]

    gen_resp = client.post("/api/v1/generations", json={"selection_id": sel_id, "force_refresh": True})
    assert gen_resp.status_code == 201
    gen_data = gen_resp.json()

    # Because 1.1 Intended Use text is identical in v1 and v2, status should be CURRENT
    assert gen_data["staleness_status"] == "CURRENT"
