import re
from typing import Any
from sqlalchemy.orm import Session
from app.models import DocumentVersion, Node

def evaluate_generation_staleness(generation_doc: dict[str, Any], db: Session) -> tuple[str, list[str]]:
    """
    Evaluates whether a test case generation is CURRENT, STALE, or DELETED
    relative to the currently active document version in the database.
    
    Returns (status, detailed_reasons).
    """
    snapshots = generation_doc.get("node_snapshots", [])
    if not snapshots:
        return "UNKNOWN", ["No node snapshots found in generation record."]

    # Fetch currently active document version
    active_version = db.query(DocumentVersion).filter(DocumentVersion.is_active == True).first()
    if not active_version:
        # Fallback to latest created version
        active_version = db.query(DocumentVersion).order_by(DocumentVersion.created_at.desc()).first()

    if not active_version:
        return "UNKNOWN", ["No document versions found in database."]

    # Load all nodes of the active document version
    active_nodes = db.query(Node).filter(Node.version_id == active_version.id).all()
    active_by_logical_id = {n.logical_node_id: n for n in active_nodes}
    active_by_path = {n.node_path: n for n in active_nodes}

    reasons = []
    is_stale = False
    has_deleted_node = False

    for snap in snapshots:
        snap_logical_id = snap.get("logical_node_id")
        snap_path = snap.get("node_path")
        snap_hash = snap.get("content_hash")
        snap_heading = snap.get("heading")

        # Find matching node in active version by logical ID or path
        active_node = active_by_logical_id.get(snap_logical_id) or active_by_path.get(snap_path)

        if not active_node:
            has_deleted_node = True
            is_stale = True
            reasons.append(
                f"Section '{snap_heading}' ({snap_path}) no longer exists in active version '{active_version.version_label}'."
            )
            continue

        if active_node.content_hash != snap_hash:
            is_stale = True
            
            # Analyze whether numbers/thresholds changed
            old_body = snap.get("body_text", "")
            new_body = active_node.body_text or ""
            old_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", old_body))
            new_nums = set(re.findall(r"\b\d+(?:\.\d+)?\b", new_body))
            
            impact_detail = ""
            if old_nums != new_nums:
                diff_nums = (new_nums - old_nums) | (old_nums - new_nums)
                impact_detail = f" [Critical Parameter Shift detected: numerical values altered ({', '.join(sorted(diff_nums)[:5])})]"

            reasons.append(
                f"Section '{active_node.heading}' was modified in '{active_version.version_label}' "
                f"(Hash {snap_hash[:8]} -> {active_node.content_hash[:8]}).{impact_detail}"
            )

    if has_deleted_node:
        return "DELETED", reasons
    elif is_stale:
        return "STALE", reasons
    else:
        return "CURRENT", [f"All {len(snapshots)} requirement section(s) match active version '{active_version.version_label}'."]
