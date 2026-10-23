import os
import pytest
from app.parser import parse_pdf_document, generate_content_hash, normalize_text

@pytest.fixture(scope="module")
def v1_nodes():
    pdf_path = "data/ct200_manual_v1.pdf"
    assert os.path.exists(pdf_path), f"Missing {pdf_path}"
    return parse_pdf_document(pdf_path)

@pytest.fixture(scope="module")
def v2_nodes():
    pdf_path = "data/ct200_manual_v2.pdf"
    assert os.path.exists(pdf_path), f"Missing {pdf_path}"
    return parse_pdf_document(pdf_path)

def test_duplicate_heading_resolution(v1_nodes):
    """
    Asserts that duplicate headings ('4.2 Error Codes' and '7.1 Error Codes')
    produce two distinct node IDs, different node paths, and different parents.
    """
    error_code_nodes = [n for n in v1_nodes if "Error Codes" in n["heading"]]
    assert len(error_code_nodes) == 2, f"Expected 2 'Error Codes' nodes, found {len(error_code_nodes)}"
    
    node1, node2 = error_code_nodes[0], error_code_nodes[1]
    assert node1["id"] != node2["id"]
    assert node1["parent_id"] != node2["parent_id"]
    assert node1["node_path"] != node2["node_path"]
    
    # Verify parent headings
    nodes_by_id = {n["id"]: n for n in v1_nodes}
    parent1 = nodes_by_id[node1["parent_id"]]
    parent2 = nodes_by_id[node2["parent_id"]]
    assert "Alarms and Safety Behavior" in parent1["heading"]
    assert "Troubleshooting" in parent2["heading"]

def test_irregular_heading_font_size(v1_nodes):
    """
    Asserts that '3.2 Cuff Inflation Sequence' is correctly identified as a Level 2
    heading despite having an irregular 11.0pt font size (while other L2 headings are 12.9pt).
    """
    cuff_seq = next((n for n in v1_nodes if "3.2" in n["heading"]), None)
    assert cuff_seq is not None, "Section 3.2 Cuff Inflation Sequence was not extracted"
    assert cuff_seq["level"] == 2
    assert "Cuff Inflation Sequence" in cuff_seq["heading"]
    
    nodes_by_id = {n["id"]: n for n in v1_nodes}
    parent = nodes_by_id[cuff_seq["parent_id"]]
    assert "3. Device Operation" in parent["heading"]

def test_hierarchy_depth_skip_handling(v1_nodes):
    """
    Asserts that '2.1.1.1 Battery Life Under Typical Use' correctly nests directly under
    '2.1 General Specifications' even though there is no intermediate '2.1.1' node.
    """
    battery_node = next((n for n in v1_nodes if "2.1.1.1" in n["heading"]), None)
    assert battery_node is not None, "Section 2.1.1.1 was not found"
    assert battery_node["level"] >= 3
    
    nodes_by_id = {n["id"]: n for n in v1_nodes}
    parent = nodes_by_id[battery_node["parent_id"]]
    assert "2.1 General Specifications" in parent["heading"]

def test_out_of_order_section_ordering(v1_nodes):
    """
    Asserts that the physical document ordering (where 3.4 appears before 3.3 in the manual)
    is preserved faithfully in the extracted node list without dropping either node.
    """
    idx_34 = next(i for i, n in enumerate(v1_nodes) if "3.4 Auto Shutoff" in n["heading"])
    idx_33 = next(i for i, n in enumerate(v1_nodes) if "3.3 Result Display and Classification" in n["heading"])
    assert idx_34 < idx_33, "Physical document order should place 3.4 before 3.3 as printed"

def test_numbered_list_items_not_misclassified_as_headings(v1_nodes):
    """
    Asserts that numbered classification items (e.g. '1. Normal: systolic < 120...')
    under Section 3.3 are preserved as body text and not incorrectly parsed as top-level headings.
    """
    sec_33 = next(n for n in v1_nodes if "3.3 Result Display" in n["heading"])
    assert "Normal: systolic < 120" in sec_33["body_text"]
    assert "Hypertensive Crisis: systolic > 180" in sec_33["body_text"]
    
    # Assert there is no separate node created for "1. Normal"
    list_as_node = any(n["heading"].startswith("1. Normal") for n in v1_nodes)
    assert not list_as_node, "Numbered list item was mistakenly parsed as a section heading"

def test_content_hash_determinism():
    """
    Asserts that the SHA-256 content hash is deterministic and whitespace-normalized.
    """
    h1 = generate_content_hash("4.1 Overpressure Protection", 2, "If cuff pressure exceeds 299 mmHg")
    h2 = generate_content_hash(" 4.1 Overpressure Protection ", 2, "If cuff pressure exceeds 299 mmHg\n")
    h3 = generate_content_hash("4.1 Overpressure Protection", 2, "If cuff pressure exceeds 300 mmHg")
    
    assert h1 == h2, "Equivalent normalized content should yield identical hashes"
    assert h1 != h3, "Modified body text must yield different hash"
