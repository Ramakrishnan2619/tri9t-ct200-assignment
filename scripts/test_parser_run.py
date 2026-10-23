import sys
import os

# Set stdout encoding to utf-8 if possible
if sys.stdout.encoding != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

from app.parser import parse_pdf_document

def run():
    print("=== Parsing V1 Manual ===")
    v1_nodes = parse_pdf_document("data/ct200_manual_v1.pdf")
    print(f"Total V1 Nodes Extracted: {len(v1_nodes)}")
    for n in v1_nodes:
        parent_info = n['parent_id'] or 'ROOT'
        body_snip = (n['body_text'][:50] + "...") if n['body_text'] else "(empty)"
        print(f"L{n['level']} [{n['id']}] {n['heading']} (Parent: {parent_info}) [Hash: {n['content_hash'][:8]}]")
        print(f"    Path: {n['node_path']}")
        print(f"    Body snippet: {body_snip}")

    print("\n=== Parsing V2 Manual ===")
    v2_nodes = parse_pdf_document("data/ct200_manual_v2.pdf")
    print(f"Total V2 Nodes Extracted: {len(v2_nodes)}")
    for n in v2_nodes:
        parent_info = n['parent_id'] or 'ROOT'
        body_snip = (n['body_text'][:50] + "...") if n['body_text'] else "(empty)"
        print(f"L{n['level']} [{n['id']}] {n['heading']} (Parent: {parent_info}) [Hash: {n['content_hash'][:8]}]")
        print(f"    Path: {n['node_path']}")
        print(f"    Body snippet: {body_snip}")

if __name__ == "__main__":
    run()
