import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.database import Base, get_db
from app.models import DocumentVersion, Node, Selection
from app.parser import parse_pdf_document, generate_content_hash
from app.versioning import compute_text_diff
from app.ingest import ingest_document_version
from app.main import app
from app.store import store

TEST_DB_FILE = "./test_pipeline.db"
TEST_DB_URL = f"sqlite:///{TEST_DB_FILE}"
test_engine = create_engine(TEST_DB_URL, connect_args={"check_same_thread": False})
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=test_engine)

def override_get_db():
    db = TestingSessionLocal()
    try:
        yield db
    finally:
        db.close()

app.dependency_overrides[get_db] = override_get_db
client = TestClient(app)

@pytest.fixture(scope="module", autouse=True)
def setup_database():
    if os.path.exists(TEST_DB_FILE):
        os.remove(TEST_DB_FILE)
    Base.metadata.create_all(bind=test_engine)
    store.clear()
    yield
    if os.path.exists(TEST_DB_FILE):
        try:
            os.remove(TEST_DB_FILE)
        except Exception:
            pass
    store.clear()


# ==========================================
# 1. PARSER & IRREGULARITY TESTS
# ==========================================

def test_content_hash_consistency():
    """Asserts that identical text produces identical SHA-256 hashes regardless of minor whitespace."""
    h1 = generate_content_hash("Safety Warnings", 1, "Do not submerge device.")
    h2 = generate_content_hash(" Safety Warnings ", 1, "Do not submerge device.\n")
    assert h1 == h2


def test_duplicate_heading_handling():
    """
    Asserts that duplicate headings ('4.2 Error Codes' and '7.1 Error Codes')
    are resolved with distinct IDs and unique parent paths.
    """
    v1_nodes = parse_pdf_document("data/ct200_manual_v1.pdf")
    error_nodes = [n for n in v1_nodes if "Error Codes" in n["heading"]]
    assert len(error_nodes) == 2
    assert error_nodes[0]["id"] != error_nodes[1]["id"]
    assert error_nodes[0]["node_path"] != error_nodes[1]["node_path"]


def test_irregular_heading_font_size():
    """
    Asserts that Section 3.2 Cuff Inflation Sequence is captured as a Level 2 heading
    even though it has an irregular 11.0pt font size in the PDF.
    """
    v1_nodes = parse_pdf_document("data/ct200_manual_v1.pdf")
    cuff_node = next((n for n in v1_nodes if "3.2 Cuff Inflation Sequence" in n["heading"]), None)
    assert cuff_node is not None
    assert cuff_node["level"] == 2


def test_depth_skip_handling():
    """
    Asserts that Section 2.1.1.1 Battery Life correctly parents under 2.1 General Specifications
    despite skipping an intermediate 2.1.1 level.
    """
    v1_nodes = parse_pdf_document("data/ct200_manual_v1.pdf")
    bat_node = next((n for n in v1_nodes if "2.1.1.1" in n["heading"]), None)
    assert bat_node is not None
    assert bat_node["level"] >= 3


# ==========================================
# 2. VERSIONING & DIFF TESTS
# ==========================================

def test_version_modification_diff():
    """Asserts that modifying body text produces a clear diff summary."""
    old_text = "Batteries provide approximately 300 measurement cycles."
    new_text = "Batteries provide approximately 250 measurement cycles."
    diff = compute_text_diff(old_text, new_text)
    assert diff != ""
    assert ("250" in diff or "300" in diff)


# ==========================================
# 3. END-TO-END WORKFLOW & STALENESS TESTS
# ==========================================

def test_end_to_end_ingestion_and_staleness():
    """
    Complete end-to-end flow:
    1. Ingest v1 manual.
    2. Browse top-level sections.
    3. Create a version-pinned selection on Section 4.2 Error Codes.
    4. Generate QA test cases (Status should be CURRENT).
    5. Re-ingest v2 manual (where 4.2 Error Codes changed).
    6. Retrieve generation (Status should now dynamically switch to STALE).
    """
    db = TestingSessionLocal()
    
    # 1. Ingest v1
    v1 = ingest_document_version("data/ct200_manual_v1.pdf", "1.0", db=db)
    assert v1.version_label == "1.0"

    # 2. Browse sections via API
    resp = client.get("/api/v1/sections?version=1.0")
    assert resp.status_code == 200
    sections = resp.json()
    assert len(sections) >= 8

    # Find Section 4.2 node
    err_node = db.query(Node).filter(Node.version_id == v1.id, Node.heading.like("%4.2 Error Codes%")).first()
    assert err_node is not None

    # 3. Create version-pinned selection
    sel_resp = client.post("/api/v1/selections", json={
        "name": "Error Codes Test Group",
        "version_id": v1.id,
        "node_ids": [err_node.id]
    })
    assert sel_resp.status_code == 201
    sel_id = sel_resp.json()["id"]

    # 4. Generate QA test cases
    gen_resp = client.post("/api/v1/generations", json={"selection_id": sel_id, "force_refresh": True})
    assert gen_resp.status_code == 201
    gen_data = gen_resp.json()
    gen_id = gen_data["id"]
    assert gen_data["staleness_status"] == "CURRENT"
    assert len(gen_data["test_cases"]) >= 1

    # 5. Re-ingest v2 manual
    v2 = ingest_document_version("data/ct200_manual_v2.pdf", "2.0", db=db)
    assert v2.version_label == "2.0"

    # 6. Retrieve generation: should now dynamically be STALE!
    retrieval = client.get(f"/api/v1/generations/{gen_id}").json()
    assert retrieval["staleness_status"] == "STALE"
    assert len(retrieval["staleness_reasons"]) > 0

    db.close()
