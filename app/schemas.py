from pydantic import BaseModel, Field
from typing import Optional, Any
from datetime import datetime

# --- Node Schemas ---

class NodeSummary(BaseModel):
    id: str
    logical_node_id: str
    heading: str
    level: int
    node_path: str
    content_hash: str
    page_number: int
    change_type: str

    model_config = {"from_attributes": True}

class NodeChildRef(BaseModel):
    id: str
    heading: str
    level: int
    node_path: str
    content_hash: str

    model_config = {"from_attributes": True}

class NodeDetail(BaseModel):
    id: str
    version_id: str
    logical_node_id: str
    heading: str
    level: int
    body_text: str
    node_path: str
    content_hash: str
    parent_id: Optional[str] = None
    page_number: int
    change_type: str
    diff_summary: Optional[str] = None
    children: list[NodeChildRef] = Field(default_factory=list)

    model_config = {"from_attributes": True}

class NodeDiffSummary(BaseModel):
    node_id: str
    logical_node_id: str
    heading: str
    node_path: str
    change_type: str
    has_changed: bool
    diff_summary: Optional[str] = None

# --- Selection Schemas ---

class SelectionCreate(BaseModel):
    name: str = Field(..., description="Descriptive identifier for this test generation selection")
    version_id: str = Field(..., description="ID of the document version to pin this selection to")
    node_ids: list[str] = Field(..., min_length=1, description="List of node IDs from that document version")

class SelectionResponse(BaseModel):
    id: str
    name: str
    version_id: str
    version_label: str
    node_ids: list[str]
    created_at: datetime

    model_config = {"from_attributes": True}

# --- LLM QA Generation Schemas ---

class TestCase(BaseModel):
    test_title: str = Field(..., description="Concise, action-oriented title for the test case")
    prerequisites: str = Field(..., description="Pre-conditions, device state, or test equipment required")
    steps: list[str] = Field(..., min_length=1, description="Step-by-step repeatable execution procedure")
    expected_result: str = Field(..., description="Exact verifiable outcome conforming to device spec")

class LLMOutputSchema(BaseModel):
    """Enforced structured JSON response contract from LLM provider."""
    test_cases: list[TestCase] = Field(..., min_length=1, description="List of 3 to 5 generated QA test cases")

class GenerationCreate(BaseModel):
    selection_id: str
    force_refresh: bool = Field(False, description="Bypasses idempotency cache to force LLM regeneration")

class NodeSnapshot(BaseModel):
    node_id: str
    logical_node_id: str
    node_path: str
    heading: str
    content_hash: str
    body_text: str

class GenerationResponse(BaseModel):
    id: str
    selection_id: str
    selection_name: str
    document_version_id: str
    context_hash: str
    test_cases: list[TestCase]
    node_snapshots: list[NodeSnapshot]
    staleness_status: str = Field(..., description="'CURRENT', 'STALE', or 'DELETED'")
    staleness_reasons: list[str] = Field(default_factory=list)
    created_at: str
    is_cached: bool = False
