import re
import hashlib
import unicodedata
import pymupdf  # PyMuPDF
import pdfplumber

def normalize_text(text: str) -> str:
    """
    Normalizes Unicode ligatures (fi, fl, ffi), special dashes, and excess whitespace.
    """
    if not text:
        return ""
    # Normalize ligatures like \ufb01 (fi), \ufb02 (fl) to standard ASCII equivalents
    norm = unicodedata.normalize("NFKD", text)
    # Replace non-breaking spaces and irregular whitespace
    norm = re.sub(r"[\xa0\u200b\s]+", " ", norm)
    return norm.strip()

def generate_content_hash(heading: str, level: int, body_text: str) -> str:
    """
    Computes a deterministic SHA-256 hash representing the node's semantic content.
    Whitespace is normalized so minor spacing artifacts don't create false staleness.
    """
    norm_heading = normalize_text(heading)
    norm_body = normalize_text(body_text)
    raw = f"{norm_heading}|{level}|{norm_body}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()

def is_heading_candidate(line_text: str, spans: list) -> tuple[bool, int, str]:
    """
    Evaluates whether a text line is a document or section heading.
    Returns (is_heading, level, cleaned_title).
    
    CT-200 structural characteristics:
    - Document Title: font size >= 20pt bold ("CardioTrack CT-200...")
    - Level 1: "1. Device Overview", "2. Physical...", etc. (size ~16.5pt bold)
    - Level 2: "1.1 Intended Use", "3.2 Cuff Inflation Sequence" (size ~12.9pt or 11pt bold with numbered prefix)
    - Level 3/4: "2.1.1.1 Battery Life Under Typical Use" (size ~11pt bold with 4-part prefix)
    
    Edge-case guards:
    - Lists inside sections like "1. Normal: systolic..." must NOT be treated as Level 1 headings
      because their font size is regular 11pt (flags != bold, font != Bold).
    """
    text = normalize_text(line_text)
    if not text:
        return False, 0, ""
    
    # Check span attributes (font size, bold)
    max_size = max((s.get("size", 0) for s in spans), default=0)
    has_bold = any(("bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16) != 0) for s in spans)
    
    # Document main title span (size >= 20pt bold without leading number)
    if max_size >= 20.0 and has_bold and not re.match(r"^\d+\.", text):
        return True, 0, text

    # Numbered heading pattern: e.g. "1. Device Overview" or "1.1 Intended Use" or "2.1.1.1 Battery..."
    # Pattern captures digits separated by dots with optional trailing dot
    num_match = re.match(r"^(\d+(?:\.\d+)*)\.?\s+(.+)$", text)
    if num_match and has_bold:
        prefix = num_match.group(1)
        depth = len(prefix.split("."))
        
        # Level 1 headings: e.g. "1. Device Overview" (depth=1, size >= 15pt)
        if depth == 1 and max_size >= 15.0:
            return True, 1, text
        
        # Level 2 headings: e.g. "1.1 Intended Use", "3.2 Cuff Inflation Sequence"
        # 3.2 in CT-200 is 11.0pt bold while others are 12.9pt bold
        if depth == 2 and (max_size >= 12.0 or (max_size >= 10.5 and has_bold)):
            return True, 2, text
            
        # Level 3/4 headings: e.g. "2.1.1.1 Battery Life Under Typical Use"
        if depth >= 3 and has_bold:
            return True, min(depth, 4), text

    return False, 0, ""

def extract_tables_by_page(pdf_path: str) -> dict[int, list[dict]]:
    """
    Extracts structured tables using pdfplumber to preserve column associations.
    Returns a dict mapping page_number (0-indexed) to list of extracted table data.
    """
    tables_by_page = {}
    try:
        with pdfplumber.open(pdf_path) as pdf:
            for page_idx, page in enumerate(pdf.pages):
                extracted = page.extract_tables()
                if extracted:
                    tables_by_page[page_idx] = []
                    for table in extracted:
                        cleaned_table = []
                        for row in table:
                            cleaned_row = [normalize_text(cell) if cell else "" for cell in row]
                            if any(cleaned_row):
                                cleaned_table.append(cleaned_row)
                        if cleaned_table:
                            tables_by_page[page_idx].append(cleaned_table)
    except Exception as e:
        print(f"Warning: table extraction fallback due to {e}")
    return tables_by_page

def format_table_as_markdown(table: list[list[str]]) -> str:
    """
    Converts a 2D table grid into standard GitHub-flavored Markdown table text.
    """
    if not table:
        return ""
    
    header = table[0]
    md_lines = []
    md_lines.append("| " + " | ".join(header) + " |")
    md_lines.append("| " + " | ".join(["---"] * len(header)) + " |")
    for row in table[1:]:
        padded_row = row + [""] * (len(header) - len(row))
        md_lines.append("| " + " | ".join(padded_row[:len(header)]) + " |")
    return "\n" + "\n".join(md_lines) + "\n"

def parse_pdf_document(pdf_path: str) -> list[dict]:
    """
    Parses a CardioTrack CT-200 manual PDF into a full hierarchical node tree.
    Returns a list of node dictionaries with parent/child links and hashes.
    """
    doc = pymupdf.open(pdf_path)
    nodes = []
    stack = []  # Stack of active parent nodes
    
    # Extract tables using pdfplumber for high-fidelity tabular data
    page_tables = extract_tables_by_page(pdf_path)
    
    node_counter = 0
    document_title_collected = False

    for page_idx in range(len(doc)):
        page = doc[page_idx]
        text_dict = page.get_text("dict")
        blocks = text_dict.get("blocks", [])
        
        # Sort blocks vertically top-to-bottom
        blocks = sorted(blocks, key=lambda b: (b["bbox"][1], b["bbox"][0]))
        
        for b in blocks:
            if b.get("type") != 0:  # non-text (e.g. image)
                continue
            
            # Special check for Page 1 multi-line Document Title (Block 0 with size >= 20)
            if page_idx == 0 and not document_title_collected:
                block_lines = b.get("lines", [])
                is_doc_title_block = False
                title_spans = []
                for l in block_lines:
                    for s in l.get("spans", []):
                        if s.get("size", 0) >= 20.0 and ("bold" in s.get("font", "").lower() or (s.get("flags", 0) & 16)):
                            is_doc_title_block = True
                            title_spans.append(s.get("text", ""))
                
                if is_doc_title_block:
                    full_title = normalize_text(" ".join(title_spans))
                    node_counter += 1
                    root_node = {
                        "id": f"node_{node_counter:03d}",
                        "heading": full_title,
                        "level": 0,
                        "body_text": "",
                        "node_path": f"/{full_title}",
                        "parent_id": None,
                        "children_ids": [],
                        "page_number": 1
                    }
                    nodes.append(root_node)
                    stack.append(root_node)
                    document_title_collected = True
                    continue

            lines = b.get("lines", [])
            for line in lines:
                spans = line.get("spans", [])
                raw_text = "".join(s.get("text", "") for s in spans)
                line_text = normalize_text(raw_text)
                if not line_text:
                    continue
                
                is_heading, level, heading_title = is_heading_candidate(line_text, spans)
                
                if is_heading:
                    node_counter += 1
                    node_id = f"node_{node_counter:03d}"
                    
                    # Pop stack until we find an active parent with strictly lower level
                    while stack and stack[-1]["level"] >= level:
                        stack.pop()
                    
                    parent_node = stack[-1] if stack else None
                    parent_id = parent_node["id"] if parent_node else None
                    parent_path = parent_node["node_path"] if parent_node else ""
                    
                    current_path = f"{parent_path}/{heading_title}" if parent_path else f"/{heading_title}"
                    
                    new_node = {
                        "id": node_id,
                        "heading": heading_title,
                        "level": level,
                        "body_text": "",
                        "node_path": current_path,
                        "parent_id": parent_id,
                        "children_ids": [],
                        "page_number": page_idx + 1
                    }
                    
                    if parent_node:
                        parent_node["children_ids"].append(node_id)
                        
                    nodes.append(new_node)
                    stack.append(new_node)
                else:
                    # Accumulate regular body text into the active node
                    if stack:
                        active_node = stack[-1]
                        if active_node["body_text"]:
                            active_node["body_text"] += " " + line_text
                        else:
                            active_node["body_text"] = line_text

    # Integrate tables into their respective section nodes based on page and context
    # Section 2.1 General Specifications on Page 2 contains Table 1
    # Section 4.2 Error Codes on Page 4 contains Table 2
    for node in nodes:
        if "2.1 General Speci" in node["heading"] and 1 in page_tables and page_tables[1]:
            table_md = format_table_as_markdown(page_tables[1][0])
            if table_md not in node["body_text"]:
                node["body_text"] = (node["body_text"] + "\n" + table_md).strip()
                
        elif "4.2 Error Codes" in node["heading"] and 3 in page_tables and page_tables[3]:
            table_md = format_table_as_markdown(page_tables[3][0])
            if table_md not in node["body_text"]:
                node["body_text"] = (node["body_text"] + "\n" + table_md).strip()

    # Compute final SHA-256 content hashes
    for n in nodes:
        n["content_hash"] = generate_content_hash(n["heading"], n["level"], n["body_text"])

    return nodes
