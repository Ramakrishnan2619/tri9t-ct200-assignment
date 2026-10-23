import os
import argparse
from sqlalchemy.orm import Session
from app.database import SessionLocal, init_db
from app.models import DocumentVersion, Node
from app.parser import parse_pdf_document
from app.versioning import match_and_diff_versions

def ingest_document_version(pdf_path: str, version_label: str, db: Session = None) -> DocumentVersion:
    """
    Ingests a PDF manual into the relational store.
    If previous versions exist, performs node alignment, change detection,
    and diff tracking without destroying earlier versions.
    """
    should_close_db = False
    if db is None:
        init_db()
        db = SessionLocal()
        should_close_db = True
        
    try:
        # Check if this version label already exists
        existing_version = db.query(DocumentVersion).filter(DocumentVersion.version_label == version_label).first()
        if existing_version:
            print(f"Version '{version_label}' already exists (ID: {existing_version.id}). Skipping re-creation.")
            return existing_version

        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found at: {pdf_path}")

        print(f"Parsing PDF document: {pdf_path} ...")
        raw_nodes = parse_pdf_document(pdf_path)
        print(f"Extracted {len(raw_nodes)} hierarchical nodes.")

        # Find existing active or latest version
        latest_version = db.query(DocumentVersion).filter(DocumentVersion.is_active == True).first()
        if not latest_version:
            latest_version = db.query(DocumentVersion).order_by(DocumentVersion.created_at.desc()).first()

        # Mark all previous versions as inactive
        db.query(DocumentVersion).update({DocumentVersion.is_active: False})

        # Create new DocumentVersion record
        doc_version = DocumentVersion(
            version_label=version_label,
            source_file=pdf_path,
            is_active=True
        )
        db.add(doc_version)
        db.flush()

        # If previous version exists, match nodes and compute diffs
        if latest_version:
            print(f"Re-ingesting against previous active version: {latest_version.version_label}")
            v1_nodes = db.query(Node).filter(Node.version_id == latest_version.id).all()
            v1_dicts = [
                {
                    "id": n.id,
                    "logical_node_id": n.logical_node_id,
                    "heading": n.heading,
                    "level": n.level,
                    "body_text": n.body_text,
                    "node_path": n.node_path,
                    "content_hash": n.content_hash,
                    "parent_id": n.parent_id
                }
                for n in v1_nodes
            ]
            enriched_nodes = match_and_diff_versions(v1_dicts, raw_nodes)
        else:
            print("First version ingestion (baseline).")
            enriched_nodes = []
            for n in raw_nodes:
                n_copy = dict(n)
                n_copy["logical_node_id"] = f"log_{n['id']}"
                n_copy["change_type"] = "NEW"
                n_copy["diff_summary"] = None
                enriched_nodes.append(n_copy)

        # First pass: Create Node objects and build mapping from raw ID to persistent DB ID
        id_mapping = {}
        node_objs = []
        for n_data in enriched_nodes:
            node_obj = Node(
                version_id=doc_version.id,
                logical_node_id=n_data["logical_node_id"],
                heading=n_data["heading"],
                level=n_data["level"],
                body_text=n_data["body_text"],
                node_path=n_data["node_path"],
                content_hash=n_data["content_hash"],
                page_number=n_data.get("page_number", 1),
                change_type=n_data.get("change_type", "NEW"),
                diff_summary=n_data.get("diff_summary")
            )
            db.add(node_obj)
            db.flush()
            id_mapping[n_data["id"]] = node_obj.id
            node_objs.append((node_obj, n_data.get("parent_id")))

        # Second pass: Link parent relationships using the new persistent DB IDs
        for node_obj, raw_parent_id in node_objs:
            if raw_parent_id and raw_parent_id in id_mapping:
                node_obj.parent_id = id_mapping[raw_parent_id]

        db.commit()
        db.refresh(doc_version)
        print(f"Successfully ingested Version '{version_label}' with {len(node_objs)} nodes.")
        return doc_version

    finally:
        if should_close_db:
            db.close()

def main():
    parser = argparse.ArgumentParser(description="Ingest CT-200 manual versions into SQLite database.")
    parser.add_argument("--file", required=True, help="Path to PDF manual file")
    parser.add_argument("--version", required=True, help="Version label (e.g. 1.0 or 2.0)")
    args = parser.parse_args()

    ingest_document_version(args.file, args.version)

if __name__ == "__main__":
    main()
