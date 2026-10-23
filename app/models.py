import uuid
from datetime import datetime, timezone
from sqlalchemy import Column, String, Integer, ForeignKey, DateTime, Text, Boolean
from sqlalchemy.orm import relationship
from app.database import Base

def generate_uuid() -> str:
    return str(uuid.uuid4())

class DocumentVersion(Base):
    """
    Represents an ingested version of the CT-200 manual (e.g. v1, v2).
    """
    __tablename__ = "document_versions"

    id = Column(String, primary_key=True, default=generate_uuid)
    version_label = Column(String, nullable=False, unique=True, index=True)
    source_file = Column(String, nullable=False)
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    is_active = Column(Boolean, default=False)  # Active / Latest version flag

    nodes = relationship("Node", back_populates="document_version", cascade="all, delete-orphan")
    selections = relationship("Selection", back_populates="document_version")

class Node(Base):
    """
    Represents a hierarchical section node in a document version.
    """
    __tablename__ = "nodes"

    id = Column(String, primary_key=True, default=generate_uuid)
    version_id = Column(String, ForeignKey("document_versions.id"), nullable=False, index=True)
    logical_node_id = Column(String, nullable=False, index=True)  # Persistent across versions for unchanged/modified nodes
    
    heading = Column(String, nullable=False, index=True)
    level = Column(Integer, nullable=False, index=True)  # 0=Document, 1=Chapter, 2=Section, etc.
    body_text = Column(Text, default="")
    node_path = Column(String, nullable=False, index=True)  # e.g. /Manual/4. Alarms/4.2 Error Codes
    content_hash = Column(String(64), nullable=False, index=True)  # SHA-256
    
    parent_id = Column(String, ForeignKey("nodes.id"), nullable=True)
    page_number = Column(Integer, default=1)
    
    # Versioning audit attributes
    change_type = Column(String, default="NEW")  # NEW, UNCHANGED, MODIFIED, ADDED, DELETED
    diff_summary = Column(Text, nullable=True)

    document_version = relationship("DocumentVersion", back_populates="nodes")
    parent = relationship("Node", remote_side=[id], backref="children")

class Selection(Base):
    """
    Represents a user-defined selection of nodes, strictly version-pinned.
    """
    __tablename__ = "selections"

    id = Column(String, primary_key=True, default=generate_uuid)
    name = Column(String, nullable=False, index=True)
    version_id = Column(String, ForeignKey("document_versions.id"), nullable=False, index=True)
    node_ids = Column(Text, nullable=False)  # JSON-encoded list of node IDs
    node_hashes = Column(Text, nullable=False)  # JSON-encoded dict of {node_id: content_hash} at time of selection
    created_at = Column(DateTime, default=lambda: datetime.now(timezone.utc))

    document_version = relationship("DocumentVersion", back_populates="selections")
