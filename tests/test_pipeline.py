import pytest
from app.parser import generate_content_hash, parse_pdf_document
from app.versioning import compute_text_diff

def test_content_hash_consistency():
    """Validates deterministic SHA-256 hash generation."""
    h1 = generate_content_hash("Safety Warnings", 1, "Do not submerge device.")
    h2 = generate_content_hash("Safety Warnings", 1, "Do not submerge device.")
    assert h1 == h2

def test_duplicate_heading_unique_paths():
    """Validates that duplicate heading titles have unique hierarchical paths."""
    v1_nodes = parse_pdf_document("data/ct200_manual_v1.pdf")
    error_code_nodes = [n for n in v1_nodes if "Error Codes" in n["heading"]]
    assert len(error_code_nodes) == 2
    assert error_code_nodes[0]["node_path"] != error_code_nodes[1]["node_path"]

def test_version_modification_detection():
    """Validates that modified body text generates a non-empty diff summary."""
    old_text = "Under typical use, batteries provide 300 cycles."
    new_text = "Under typical use, batteries provide 250 cycles."
    diff = compute_text_diff(old_text, new_text)
    assert diff != ""
    assert ("250" in diff or "300" in diff)
