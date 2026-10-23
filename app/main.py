import json
import hashlib
from typing import Optional
from fastapi import FastAPI, Depends, HTTPException, Query, status
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from sqlalchemy import or_

from app.database import get_db, init_db
from app.models import DocumentVersion, Node, Selection
from app.schemas import (
    NodeSummary,
    NodeDetail,
    NodeDiffSummary,
    SelectionCreate,
    SelectionResponse,
    GenerationCreate,
    GenerationResponse,
    NodeSnapshot,
    TestCase
)
from app.store import store
from app.llm import generate_qa_test_cases
from app.staleness import evaluate_generation_staleness
from app.ingest import ingest_document_version

# Initialize database tables
init_db()

app = FastAPI(
    title="CardioTrack CT-200 Traceability & QA Engine",
    description="Regulatory-grade document versioning, hierarchical browsing, and LLM test case generation with staleness tracking.",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/", tags=["Health"])
def health_check():
    return {
        "status": "online",
        "service": "CardioTrack CT-200 Traceability API",
        "standard": "IEC 62304 Medical Device Software Verification"
    }

# --- Document Versions Endpoints ---

@app.get("/api/v1/versions", tags=["Versions"])
def list_versions(db: Session = Depends(get_db)):
    """Lists all ingested document versions with active version indicator."""
    versions = db.query(DocumentVersion).order_by(DocumentVersion.created_at.desc()).all()
    return [
        {
            "id": v.id,
            "version_label": v.version_label,
            "source_file": v.source_file,
            "is_active": v.is_active,
            "created_at": v.created_at.isoformat(),
            "node_count": len(v.nodes)
        }
        for v in versions
    ]

@app.post("/api/v1/ingest", status_code=status.HTTP_201_CREATED, tags=["Versions"])
def trigger_ingestion(
    file_path: str = Query(..., description="Path to PDF manual, e.g. data/ct200_manual_v1.pdf"),
    version_label: str = Query(..., description="Version label, e.g. 1.0 or 2.0"),
    db: Session = Depends(get_db)
):
    """Ingests a PDF manual as a new document version."""
    try:
        doc_ver = ingest_document_version(file_path, version_label, db=db)
        return {
            "message": f"Successfully ingested version {version_label}",
            "version_id": doc_ver.id,
            "version_label": doc_ver.version_label,
            "is_active": doc_ver.is_active
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

# --- Browse API ---

@app.get("/api/v1/sections", response_model=list[NodeSummary], tags=["Browse"])
def list_top_level_sections(
    version: Optional[str] = Query("latest", description="Version label or 'latest'"),
    db: Session = Depends(get_db)
):
    """
    Lists top-level sections (Level 1 chapters) for a specified or latest document version.
    """
    if version == "latest" or not version:
        ver = db.query(DocumentVersion).filter(DocumentVersion.is_active == True).first()
        if not ver:
            ver = db.query(DocumentVersion).order_by(DocumentVersion.created_at.desc()).first()
    else:
        ver = db.query(DocumentVersion).filter(DocumentVersion.version_label == version).first()

    if not ver:
        raise HTTPException(status_code=404, detail=f"Document version '{version}' not found.")

    sections = db.query(Node).filter(Node.version_id == ver.id, Node.level == 1).order_by(Node.id).all()
    return sections

@app.get("/api/v1/nodes", response_model=list[NodeSummary], tags=["Browse"])
def search_nodes(
    q: Optional[str] = Query(None, description="Search query across heading and body text"),
    version: Optional[str] = Query("latest", description="Version label or 'latest'"),
    level: Optional[int] = Query(None, description="Filter by hierarchical level (0, 1, 2, 3)"),
    db: Session = Depends(get_db)
):
    """
    Searches and filters nodes across headings or body text.
    """
    if version == "latest" or not version:
        ver = db.query(DocumentVersion).filter(DocumentVersion.is_active == True).first()
        if not ver:
            ver = db.query(DocumentVersion).order_by(DocumentVersion.created_at.desc()).first()
    else:
        ver = db.query(DocumentVersion).filter(DocumentVersion.version_label == version).first()

    if not ver:
        raise HTTPException(status_code=404, detail=f"Document version '{version}' not found.")

    query = db.query(Node).filter(Node.version_id == ver.id)

    if level is not None:
        query = query.filter(Node.level == level)

    if q:
        search_filter = or_(
            Node.heading.ilike(f"%{q}%"),
            Node.body_text.ilike(f"%{q}%")
        )
        query = query.filter(search_filter)

    return query.order_by(Node.id).all()

@app.get("/api/v1/nodes/{node_id}", response_model=NodeDetail, tags=["Browse"])
def get_node_by_id(node_id: str, db: Session = Depends(get_db)):
    """
    Retrieves a specific node by ID, including its children, full text, and content hash.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")

    children = db.query(Node).filter(Node.parent_id == node.id).order_by(Node.id).all()
    return NodeDetail(
        id=node.id,
        version_id=node.version_id,
        logical_node_id=node.logical_node_id,
        heading=node.heading,
        level=node.level,
        body_text=node.body_text,
        node_path=node.node_path,
        content_hash=node.content_hash,
        parent_id=node.parent_id,
        page_number=node.page_number,
        change_type=node.change_type,
        diff_summary=node.diff_summary,
        children=children
    )

@app.get("/api/v1/nodes/{node_id}/diff", response_model=NodeDiffSummary, tags=["Browse"])
def get_node_diff(node_id: str, db: Session = Depends(get_db)):
    """
    Returns whether a node has changed across versions, with lightweight diff summary.
    """
    node = db.query(Node).filter(Node.id == node_id).first()
    if not node:
        raise HTTPException(status_code=404, detail=f"Node '{node_id}' not found.")

    has_changed = (node.change_type in ["MODIFIED", "ADDED", "DELETED"])

    return NodeDiffSummary(
        node_id=node.id,
        logical_node_id=node.logical_node_id,
        heading=node.heading,
        node_path=node.node_path,
        change_type=node.change_type,
        has_changed=has_changed,
        diff_summary=node.diff_summary
    )

# --- Selection API ---

@app.post("/api/v1/selections", response_model=SelectionResponse, status_code=status.HTTP_201_CREATED, tags=["Selections"])
def create_selection(req: SelectionCreate, db: Session = Depends(get_db)):
    """
    Creates a version-pinned selection of node IDs.
    Old selections resolve to the exact version text they were created against.
    """
    ver = db.query(DocumentVersion).filter(DocumentVersion.id == req.version_id).first()
    if not ver:
        raise HTTPException(status_code=404, detail=f"Document version '{req.version_id}' not found.")

    # Validate that all requested node IDs belong to this version
    nodes = db.query(Node).filter(Node.id.in_(req.node_ids), Node.version_id == ver.id).all()
    found_ids = {n.id for n in nodes}
    missing = set(req.node_ids) - found_ids
    if missing:
        raise HTTPException(
            status_code=400,
            detail=f"The following node IDs do not belong to version '{ver.version_label}': {list(missing)}"
        )

    # Record exact content hashes at selection time
    node_hashes = {n.id: n.content_hash for n in nodes}

    selection = Selection(
        name=req.name,
        version_id=ver.id,
        node_ids=json.dumps(req.node_ids),
        node_hashes=json.dumps(node_hashes)
    )
    db.add(selection)
    db.commit()
    db.refresh(selection)

    return SelectionResponse(
        id=selection.id,
        name=selection.name,
        version_id=selection.version_id,
        version_label=ver.version_label,
        node_ids=req.node_ids,
        created_at=selection.created_at
    )

@app.get("/api/v1/selections/{selection_id}", tags=["Selections"])
def get_selection(selection_id: str, db: Session = Depends(get_db)):
    """Retrieves selection details and its pinned node snapshots."""
    sel = db.query(Selection).filter(Selection.id == selection_id).first()
    if not sel:
        raise HTTPException(status_code=404, detail=f"Selection '{selection_id}' not found.")

    node_ids = json.loads(sel.node_ids)
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).all()

    return {
        "id": sel.id,
        "name": sel.name,
        "version_id": sel.version_id,
        "version_label": sel.document_version.version_label,
        "created_at": sel.created_at.isoformat(),
        "nodes": [
            {
                "id": n.id,
                "heading": n.heading,
                "node_path": n.node_path,
                "content_hash": n.content_hash,
                "body_text": n.body_text
            }
            for n in nodes
        ]
    }

# --- LLM QA Generation & Retrieval API ---

@app.post("/api/v1/generations", response_model=GenerationResponse, status_code=status.HTTP_201_CREATED, tags=["Generations"])
def generate_test_cases(req: GenerationCreate, db: Session = Depends(get_db)):
    """
    Generates 3 to 5 QA test cases for a version-pinned selection.
    Guarantees structured output, survives document re-versioning,
    and implements deterministic idempotency caching.
    """
    sel = db.query(Selection).filter(Selection.id == req.selection_id).first()
    if not sel:
        raise HTTPException(status_code=404, detail=f"Selection '{req.selection_id}' not found.")

    node_ids = json.loads(sel.node_ids)
    nodes = db.query(Node).filter(Node.id.in_(node_ids)).order_by(Node.id).all()

    if not nodes:
        raise HTTPException(status_code=400, detail="Selection references no valid nodes.")

    # Reconstruct combined context text and calculate context hash
    context_chunks = []
    node_snapshots = []
    for n in nodes:
        context_chunks.append(f"SECTION: {n.heading}\nPATH: {n.node_path}\nCONTENT:\n{n.body_text}")
        node_snapshots.append(NodeSnapshot(
            node_id=n.id,
            logical_node_id=n.logical_node_id,
            node_path=n.node_path,
            heading=n.heading,
            content_hash=n.content_hash,
            body_text=n.body_text
        ).model_dump())

    combined_context = "\n\n---\n\n".join(context_chunks)
    context_hash = hashlib.sha256(combined_context.encode("utf-8")).hexdigest()

    # Idempotency check: Return existing generation if same selection & context hash
    if not req.force_refresh:
        existing = store.find_by_selection_and_hash(sel.id, context_hash)
        if existing:
            status_val, reasons = evaluate_generation_staleness(existing, db)
            return GenerationResponse(
                id=existing["id"],
                selection_id=existing["selection_id"],
                selection_name=existing["selection_name"],
                document_version_id=existing["document_version_id"],
                context_hash=existing["context_hash"],
                test_cases=[TestCase(**tc) for tc in existing["test_cases"]],
                node_snapshots=[NodeSnapshot(**ns) for ns in existing["node_snapshots"]],
                staleness_status=status_val,
                staleness_reasons=reasons,
                created_at=existing["created_at"],
                is_cached=True
            )

    # Call LLM generation with Pydantic validation & retries
    test_cases, prompt_used = generate_qa_test_cases(combined_context)

    # Persist in NoSQL Document Store
    record = {
        "selection_id": sel.id,
        "selection_name": sel.name,
        "document_version_id": sel.version_id,
        "context_hash": context_hash,
        "prompt_used": prompt_used,
        "test_cases": [tc.model_dump() for tc in test_cases],
        "node_snapshots": node_snapshots
    }
    saved_doc = store.insert(record)

    # Evaluate staleness at retrieval
    status_val, reasons = evaluate_generation_staleness(saved_doc, db)

    return GenerationResponse(
        id=saved_doc["id"],
        selection_id=saved_doc["selection_id"],
        selection_name=saved_doc["selection_name"],
        document_version_id=saved_doc["document_version_id"],
        context_hash=saved_doc["context_hash"],
        test_cases=test_cases,
        node_snapshots=[NodeSnapshot(**ns) for ns in node_snapshots],
        staleness_status=status_val,
        staleness_reasons=reasons,
        created_at=saved_doc["created_at"],
        is_cached=False
    )

@app.get("/api/v1/generations/{generation_id}", response_model=GenerationResponse, tags=["Generations"])
def get_generation_by_id(generation_id: str, db: Session = Depends(get_db)):
    """
    Fetches a previously generated test case set with dynamic staleness evaluation.
    """
    doc = store.get_by_id(generation_id)
    if not doc:
        raise HTTPException(status_code=404, detail=f"Generation '{generation_id}' not found.")

    status_val, reasons = evaluate_generation_staleness(doc, db)

    return GenerationResponse(
        id=doc["id"],
        selection_id=doc["selection_id"],
        selection_name=doc.get("selection_name", "Unnamed"),
        document_version_id=doc["document_version_id"],
        context_hash=doc["context_hash"],
        test_cases=[TestCase(**tc) for tc in doc["test_cases"]],
        node_snapshots=[NodeSnapshot(**ns) for ns in doc.get("node_snapshots", [])],
        staleness_status=status_val,
        staleness_reasons=reasons,
        created_at=doc["created_at"],
        is_cached=True
    )

@app.get("/api/v1/generations/by-selection/{selection_id}", response_model=list[GenerationResponse], tags=["Generations"])
def get_generations_by_selection(selection_id: str, db: Session = Depends(get_db)):
    """Retrieves all generations for a selection with active staleness detection."""
    docs = store.find_by_selection_id(selection_id)
    results = []
    for doc in docs:
        status_val, reasons = evaluate_generation_staleness(doc, db)
        results.append(GenerationResponse(
            id=doc["id"],
            selection_id=doc["selection_id"],
            selection_name=doc.get("selection_name", "Unnamed"),
            document_version_id=doc["document_version_id"],
            context_hash=doc["context_hash"],
            test_cases=[TestCase(**tc) for tc in doc["test_cases"]],
            node_snapshots=[NodeSnapshot(**ns) for ns in doc.get("node_snapshots", [])],
            staleness_status=status_val,
            staleness_reasons=reasons,
            created_at=doc["created_at"],
            is_cached=True
        ))
    return results

@app.get("/api/v1/generations/by-node/{node_id}", response_model=list[GenerationResponse], tags=["Generations"])
def get_generations_by_node(node_id: str, db: Session = Depends(get_db)):
    """Retrieves all generations that depended on a specific node ID."""
    docs = store.find_by_node_id(node_id)
    results = []
    for doc in docs:
        status_val, reasons = evaluate_generation_staleness(doc, db)
        results.append(GenerationResponse(
            id=doc["id"],
            selection_id=doc["selection_id"],
            selection_name=doc.get("selection_name", "Unnamed"),
            document_version_id=doc["document_version_id"],
            context_hash=doc["context_hash"],
            test_cases=[TestCase(**tc) for tc in doc["test_cases"]],
            node_snapshots=[NodeSnapshot(**ns) for ns in doc.get("node_snapshots", [])],
            staleness_status=status_val,
            staleness_reasons=reasons,
            created_at=doc["created_at"],
            is_cached=True
        ))
    return results
