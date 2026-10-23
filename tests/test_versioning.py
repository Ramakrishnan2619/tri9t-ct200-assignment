import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from app.database import Base
from app.models import DocumentVersion, Node
from app.ingest import ingest_document_version

@pytest.fixture
def test_db():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False})
    Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()

def test_v1_to_v2_versioning_and_node_retention(test_db):
    """
    Asserts that:
    1. Re-ingesting v2 creates a new DocumentVersion without destroying v1.
    2. Unchanged nodes retain the same logical_node_id.
    3. Modified nodes are correctly flagged as MODIFIED with diff summaries.
    4. Added nodes are flagged as ADDED.
    """
    # 1. Ingest v1
    v1 = ingest_document_version("data/ct200_manual_v1.pdf", "1.0", db=test_db)
    assert v1.is_active is True
    assert v1.version_label == "1.0"
    
    v1_nodes = test_db.query(Node).filter(Node.version_id == v1.id).all()
    assert len(v1_nodes) == 28

    # 2. Ingest v2
    v2 = ingest_document_version("data/ct200_manual_v2.pdf", "2.0", db=test_db)
    assert v2.is_active is True
    
    # Assert v1 still exists and is now inactive
    test_db.refresh(v1)
    assert v1.is_active is False
    v1_nodes_still_exist = test_db.query(Node).filter(Node.version_id == v1.id).all()
    assert len(v1_nodes_still_exist) == 28, "Version 1 nodes must be preserved intact"

    # Inspect v2 nodes
    v2_nodes = test_db.query(Node).filter(Node.version_id == v2.id).all()
    assert len(v2_nodes) == 29, "Version 2 should contain 29 nodes (including added 5.3 Data Export)"

    v1_map = {n.node_path: n for n in v1_nodes_still_exist}
    v2_map = {n.node_path: n for n in v2_nodes}

    # Verify unchanged node: 1.1 Intended Use
    path_intended_use = next(p for p in v1_map if "1.1 Intended Use" in p)
    v1_iu = v1_map[path_intended_use]
    v2_iu = v2_map[path_intended_use]
    assert v2_iu.change_type == "UNCHANGED"
    assert v2_iu.logical_node_id == v1_iu.logical_node_id
    assert v2_iu.content_hash == v1_iu.content_hash

    # Verify modified node: 2.1.1.1 Battery Life
    path_battery = next(p for p in v1_map if "2.1.1.1" in p)
    v1_bat = v1_map[path_battery]
    v2_bat = v2_map[path_battery]
    assert v2_bat.change_type == "MODIFIED"
    assert v2_bat.logical_node_id == v1_bat.logical_node_id
    assert v2_bat.content_hash != v1_bat.content_hash
    assert v2_bat.diff_summary is not None
    assert "250" in v2_bat.diff_summary or "300" in v2_bat.diff_summary

    # Verify modified node: 3.2 Cuff Inflation Sequence (40 mmHg -> 30 mmHg)
    path_cuff = next(p for p in v1_map if "3.2 Cuff Inflation Sequence" in p)
    v1_cuff = v1_map[path_cuff]
    v2_cuff = v2_map[path_cuff]
    assert v2_cuff.change_type == "MODIFIED"
    assert v2_cuff.logical_node_id == v1_cuff.logical_node_id
    assert v2_cuff.content_hash != v1_cuff.content_hash

    # Verify newly added node in v2: 5.3 Data Export
    path_export = next(p for p in v2_map if "5.3 Data Export" in p)
    v2_export = v2_map[path_export]
    assert v2_export.change_type == "ADDED"
    assert path_export not in v1_map
