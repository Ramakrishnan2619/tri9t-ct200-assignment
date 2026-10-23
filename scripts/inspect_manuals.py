import os
import fitz

def inspect_pdf(path, output_txt):
    if not os.path.exists(path):
        print(f"File not found: {path}")
        return
    
    with open(output_txt, "w", encoding="utf-8") as out:
        out.write(f"=== Inspecting {path} ===\n")
        doc = fitz.open(path)
        out.write(f"Total Pages: {len(doc)}\n\n")
        
        for pno in range(len(doc)):
            page = doc[pno]
            text_page = page.get_text("dict")
            out.write(f"--- Page {pno+1} (rect: {page.rect}) ---\n")
            
            for b_idx, b in enumerate(text_page.get("blocks", [])):
                b_type = b.get("type", 0)
                bbox = b.get("bbox", [])
                if b_type == 0:  # text
                    for l_idx, line in enumerate(b.get("lines", [])):
                        line_text = "".join(s.get("text", "") for s in line.get("spans", [])).strip()
                        spans_info = " | ".join(
                            f"size={s.get('size', 0):.1f}, font={s.get('font')}, flags={s.get('flags')}, color={s.get('color')}"
                            for s in line.get("spans", [])
                        )
                        out.write(f"  [Block {b_idx} L{l_idx}] bbox={bbox} [{spans_info}] -> {line_text}\n")
                elif b_type == 1:  # image
                    out.write(f"  [IMAGE BLOCK {b_idx}] bbox={bbox} width={b.get('width')} height={b.get('height')}\n")
            out.write("\n")
    print(f"Inspection written to {output_txt}")

if __name__ == "__main__":
    os.makedirs("inspect_logs", exist_ok=True)
    inspect_pdf("data/ct200_manual.pdf", "inspect_logs/v1_structure.txt")
    inspect_pdf("data/ct200_manual_v2.pdf", "inspect_logs/v2_structure.txt")
