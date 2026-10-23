import difflib
from typing import Any

def compute_text_diff(old_text: str, new_text: str) -> str:
    """
    Produces a readable line/word diff summary between two text versions.
    """
    old_lines = old_text.splitlines(keepends=True)
    new_lines = new_text.splitlines(keepends=True)
    diff = list(difflib.unified_diff(
        old_lines, new_lines,
        fromfile="v1", tofile="v2",
        lineterm=""
    ))
    if not diff:
        # If line diff is empty (e.g. single long paragraph modified), do word-level diff
        old_words = old_text.split()
        new_words = new_text.split()
        matcher = difflib.SequenceMatcher(None, old_words, new_words)
        changes = []
        for tag, i1, i2, j1, j2 in matcher.get_opcodes():
            if tag == "replace":
                changes.append(f"Replaced '{' '.join(old_words[i1:i2])}' with '{' '.join(new_words[j1:j2])}'")
            elif tag == "delete":
                changes.append(f"Removed '{' '.join(old_words[i1:i2])}'")
            elif tag == "insert":
                changes.append(f"Added '{' '.join(new_words[j1:j2])}'")
        return "; ".join(changes) if changes else "Body text modified."
    return "\n".join(diff)

def match_and_diff_versions(v1_nodes: list[dict[str, Any]], v2_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Aligns v2 nodes with v1 nodes to assign persistent logical_node_id,
    detect changes (UNCHANGED, MODIFIED, ADDED, DELETED), and attach diff summaries.
    
    Returns enriched v2 node dictionaries ready for persistence.
    """
    v1_by_path = {n["node_path"]: n for n in v1_nodes}
    v1_paths = set(v1_by_path.keys())
    matched_v1_paths = set()
    
    enriched_v2_nodes = []
    
    for v2_node in v2_nodes:
        node_path = v2_node["node_path"]
        v2_copy = dict(v2_node)
        
        if node_path in v1_by_path:
            v1_node = v1_by_path[node_path]
            matched_v1_paths.add(node_path)
            
            # Inherit logical node identity to link across versions
            v2_copy["logical_node_id"] = v1_node.get("logical_node_id") or v1_node.get("id")
            
            if v1_node["content_hash"] == v2_node["content_hash"]:
                v2_copy["change_type"] = "UNCHANGED"
                v2_copy["diff_summary"] = None
            else:
                v2_copy["change_type"] = "MODIFIED"
                v2_copy["diff_summary"] = compute_text_diff(v1_node.get("body_text", ""), v2_node.get("body_text", ""))
        else:
            # Check for candidate renamed heading under same parent
            parent_id = v2_node.get("parent_id")
            v2_copy["logical_node_id"] = f"log_{v2_node['id']}"
            v2_copy["change_type"] = "ADDED"
            v2_copy["diff_summary"] = f"Newly added section: '{v2_node['heading']}'"
            
        enriched_v2_nodes.append(v2_copy)
        
    return enriched_v2_nodes

def get_deleted_v1_nodes(v1_nodes: list[dict[str, Any]], v2_nodes: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Identifies any sections present in v1 that were deleted or absent in v2.
    """
    v2_paths = {n["node_path"] for n in v2_nodes}
    deleted = []
    for n in v1_nodes:
        if n["node_path"] not in v2_paths:
            del_node = dict(n)
            del_node["change_type"] = "DELETED"
            deleted.append(del_node)
    return deleted
