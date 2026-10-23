# Engineering Approach & Architecture Document

**Project:** CardioTrack CT-200 Versioned Traceability & QA Test Generation Pipeline  
**Role:** AI Engineer Intern — Tri9T AI  
**Author:** AI Engineering Applicant  

---

## 1. Executive Summary & Problem Understanding

In medical device software quality assurance (governed by standards such as **IEC 62304** and **FDA 21 CFR Part 820**), every verification test case must establish bidirectional traceability to a specific requirement or technical specification. 

A critical failure mode in regulated MedTech development is **stale traceability**: when an engineering manual or requirement specification changes across versions (e.g., from v1.0 to v2.0), previously generated test cases may quietly become outdated, misleading, or unsafe. 

This system delivers an end-to-end solution for the fictional **CardioTrack CT-200 Home Blood Pressure Monitor**, implementing:
1. An **OCR/Layout-aware PDF parsing engine** that reconstructs document hierarchies while handling structural irregularities without silent data loss.
2. A **Document Versioning & Node Alignment Engine** that supports re-ingestion of updated manuals, recognizing unchanged nodes without duplication, detecting body text modifications, and assigning persistent logical identities.
3. A **Version-Pinned Selection API** that binds test groups to immutable document snapshots.
4. An **LLM QA Test Case Generation Engine** with strict Pydantic validation, self-correction retry loops, and deterministic fallback mechanics.
5. A **Dynamic Staleness & Impact Detection Engine** that evaluates hash parity and numerical parameter shifts at query time.

---

## 2. Document Extraction & Hierarchy Reconstruction

### 2.1 Tooling & Parser Selection
We evaluated several PDF processing libraries:
- Generic text extraction (e.g. standard `pypdf`) strips font sizes and positional metadata, destroying the document hierarchy and flattening multi-column tables.
- **Selected Approach:** A dual-engine pipeline combining **PyMuPDF (`pymupdf`)** for typography, font flags, and span bounding boxes with **`pdfplumber`** for table isolation.

### 2.2 Hierarchy Reconstruction Strategy
Text blocks are traversed in physical reading order (spatially sorted by $y_0 \to x_0$ coordinates). Headings are classified through a hybrid heuristic combining font size, font weight flags, and numbering prefixes:
- **Document Title (Level 0):** Bold text with font size $\ge 20.0\,\text{pt}$ lacking a section prefix (e.g. *"CardioTrack CT-200 Home Blood Pressure Monitor — Technical & User Manual"*).
- **Major Chapters (Level 1):** Bold text with single-integer prefix (e.g. `1. Device Overview`, `4. Alarms and Safety Behavior`) and font size $\ge 15.0\,\text{pt}$.
- **Sections (Level 2):** Bold text with two-tier prefix (e.g. `1.1 Intended Use`, `4.2 Error Codes`).
- **Subsections (Level 3/4):** Bold text with 3+ prefix tiers (e.g. `2.1.1.1 Battery Life Under Typical Use`).

Hierarchy is maintained using an active depth stack:
- When a heading of depth $D$ is encountered, the stack is popped until the top element has depth $< D$.
- The current node is assigned as a child of the top stack element and pushed onto the stack.
- Subsequent non-heading body text lines and table markdown are accumulated into the active stack node's `body_text`.

### 2.3 Structural Inconsistencies & Edge Cases Handled

| Irregularity in CT-200 PDF | Why Naive Parsers Fail | Our Engineering Solution |
| :--- | :--- | :--- |
| **Duplicate Headings** (`4.2 Error Codes` and `7.1 Error Codes`) | Keying nodes by title alone causes collisions or overwrites. | Nodes are assigned UUIDs and identified by canonical paths (`/.../4. Alarms/4.2 Error Codes` vs `/.../7. Troubleshooting/7.1 Error Codes`). |
| **Irregular Heading Font Size** (`3.2 Cuff Inflation Sequence`) | Level 2 headings are normally $12.9\,\text{pt}$, but `3.2` is printed at $11.0\,\text{pt}$ bold. A naive threshold misses it as body text. | Regex-assisted prefix detection (`^(\d+(?:\.\d+)*)\.?\s+`) combined with font bold flag (`flags & 16` or `bold` in font name) catches `3.2` as Level 2. |
| **Hierarchy Depth Skipping** (`2.1.1.1 Battery Life`) | The document jumps from `2.1` directly to `2.1.1.1` without an intermediate `2.1.1`. | The active stack checks strict inequality (`stack[-1].level >= level`). When jumping to Level 4, `2.1` (Level 2) remains on top, correctly parenting `2.1.1.1`. |
| **Out-of-Order Numbering** (`3.4 Auto Shutoff` before `3.3 Result Display`) | Sorting by section numbering would corrupt the true manual reading layout. | Physical document block ordering is preserved chronologically as printed. |
| **Numbered Lists in Body** (`1. Normal: systolic < 120...` under `3.3`) | Naive regex matching `1.` misclassifies list items as top-level Level 1 chapters. | List items possess non-bold regular font weight (`flags == 4`, font `NimbusSans-Regular`) and are preserved as body text. |
| **Unicode Ligatures** (`fi`, `fl`, `ffi`) | Rendered as Unicode private glyphs (`\ufb01`, `\ufb02`), breaking search and string equality. | Applied `unicodedata.normalize("NFKD", text)` and whitespace normalization. |
| **Tabular Data** (Specs table on p. 2, Error codes on p. 4) | Multi-column text blocks get flattened out of order. | Extracted with `pdfplumber` and converted to clean markdown table representations. |

### 2.4 Content Hashing
Each node computes a deterministic SHA-256 hash:
$$\text{ContentHash} = \text{SHA-256}(\text{normalize}(\text{Heading}) \parallel \text{Level} \parallel \text{normalize}(\text{BodyText}))$$
Whitespace normalization prevents formatting and line-break artifacts from causing false staleness triggers.

---

## 3. Document Versioning & Node Alignment Strategy

### 3.1 Data Model
- **`DocumentVersion`**: Stores `id`, `version_label` ("1.0", "2.0"), `source_file`, `created_at`, and `is_active`.
- **`Node`**: Belongs to a `DocumentVersion` and contains `id`, `logical_node_id`, `heading`, `level`, `body_text`, `node_path`, `content_hash`, `parent_id`, `change_type`, and `diff_summary`.

### 3.2 Matching Strategy
When `ct200_manual_v2.pdf` is re-ingested:
1. Earlier versions are marked `is_active = False` while preserving their records and relational integrity intact.
2. Nodes in v2 are matched against the latest previous version using **Hierarchical Path Matching**:
   - **`UNCHANGED`**: Path exists in v1 AND `v1.content_hash == v2.content_hash`. The v2 node inherits `v1.logical_node_id`.
   - **`MODIFIED`**: Path exists in v1 AND `v1.content_hash != v2.content_hash`. The v2 node inherits `v1.logical_node_id`. A diff summary is computed via `difflib`.
   - **`ADDED`**: Path exists in v2 but not in v1 (e.g. `5.3 Data Export`). A new `logical_node_id` is assigned.
   - **`DELETED`**: Path exists in v1 but is absent in v2.

### 3.3 Known Failure Modes of Path-Based Matching
- **Heading Renaming:** If `3.1 Powering On and Profile Selection` were renamed to `3.1 Power Button and Profile Modes`, path matching treats this as one `DELETED` node and one `ADDED` node. Descendant nodes would also see path divergence.
- **Production Solution with More Time:** Combine path matching with **tree-edit distance (Zhang-Shasha algorithm)** and semantic embeddings (e.g. cosine similarity $\ge 0.88$ on heading text) to detect moved or renamed sections.

---

## 4. LLM Generation Pipeline & Reliability Design

### 4.1 Prompt Design
The prompt assigns the LLM the role of an IEC 62304 Medical Device QA Engineer and supplies the concatenated text of the selection. It explicitly mandates:
- Actionable, repeatable test titles, prerequisites, numbered steps, and verifiable expected results.
- Nominal operations, boundary conditions, and safety faults (e.g. overpressure deflation, motion artifacts).
- Zero conversational commentary outside of a strict JSON schema.

### 4.2 Guardrails & Self-Correction
1. **Pydantic Schema Validation:** The LLM output is parsed through `LLMOutputSchema` enforcing:
   - `test_title`: string
   - `prerequisites`: string
   - `steps`: list of strings ($\ge 1$)
   - `expected_result`: string
2. **Error Feedback & Retry Loop:** If parsing fails or fields are missing, the system catches the `ValidationError`, appends the exact error message to the prompt, and retries with exponential backoff (up to 3 attempts).
3. **Deterministic Safety Fallback:** If an external LLM provider experiences an outage or exhausts retries, the system falls back to a deterministic domain QA generator for the CT-200. The API never crashes or returns unvalidated output.
4. **Idempotency Policy:** Re-submitting the same selection with identical context text returns the existing generation record (`is_cached=True`), preventing duplicate API cost. Setting `force_refresh=True` bypasses the cache.

---

## 5. Staleness & Impact Detection Engine

### 5.1 The Stale Traceability Problem
When a test case was generated against v1.0 specifications and v2.0 is subsequently ingested, the test case may test outdated behavior:
- In CT-200 v1.0, deflation occurs in $40\,\text{mmHg}$ increments; in v2.0, this was revised downward to $30\,\text{mmHg}$.
- In CT-200 v1.0, overpressure E3 deflates within $2.0\,\text{s}$; in v2.0, within $1.5\,\text{s}$.
- In CT-200 v1.0, low battery triggers at $<15\%$; in v2.0, at $<10\%$.

### 5.2 Resolution Mechanism
1. Every generation persists immutable **node snapshots** (`node_id`, `logical_node_id`, `node_path`, `content_hash`, `heading`, `body_text`) captured at generation time.
2. At retrieval time (`GET /api/v1/generations/{id}`), the engine queries the currently active document version and compares hashes:
   - **`CURRENT`:** All snapshot content hashes match active node hashes.
   - **`STALE`:** At least one snapshot node has a different content hash in the active version.
   - **`DELETED`:** A snapshot node's path or logical ID is absent from the active version.
3. **Parameter Shift Analysis:** The engine analyzes numerical token differences between versions to highlight critical threshold changes (e.g. `Critical Parameter Shift: numerical values altered (1.5, 2)`).

---

## 6. Decision Log (Direct Questions)

### Question 1: What's the one part of this system most likely to silently give wrong results without erroring? How would you catch it?
**Answer:**  
**Silent hierarchy mis-parenting during PDF parsing.** If a critical safety warning heading is visually indistinguishable from bold body text, the parser may fail to trigger a new node and instead append the text to the preceding section's body. The API still returns HTTP 200 OK and database operations succeed, but downstream LLM prompts receive fragmented context and test cases map to the wrong requirement. I caught and prevent this using explicit unit tests asserting that duplicated and irregular headings (such as `3.2` and `4.2 Error Codes`) produce distinct node IDs, exact parent IDs, and invariant child counts matching manual ground truth.

### Question 2: Where did you choose simplicity over correctness because of time, and what would break first if this went to production as-is?
**Answer:**  
**Path-based node matching across versions instead of fuzzy tree-edit distance.** We match nodes between v1 and v2 using exact hierarchical paths (`/Title/Chapter/Section`). In production, if a technical writer renames a high-level chapter heading (e.g., from *"4. Alarms and Safety Behavior"* to *"4. Alarms, Safety & Warnings"*), exact path matching breaks for every child subsection under that chapter. The system would misclassify all children as `DELETED` + `ADDED` rather than `MOVED/RENAMED`, temporarily severing historical staleness continuity.

### Question 3: Name one input (to your parser, your versioning matcher, or your LLM call) that you did NOT handle, and what your system does when it sees it.
**Answer:**  
**Embedded non-text vector schematics and raster diagrams.** When encountering visual circuit diagrams or mechanical pneumatic flowcharts that contain zero extractable text spans, the parser skips image block rendering. The system processes the surrounding text hierarchy without crashing, but visual test verification details are not transferred into the LLM context.

---

## 7. What Would Be Done Differently With More Time
1. **Semantic Tree Alignment:** Integrate Levenshtein distance on headings with sentence-transformer embeddings to maintain unbroken node lineage even when sections are rephrased or rearranged.
2. **Visual Layout Understanding:** Deploy an open-source layout model (such as LayoutLMv3 or Table-Transformer) to parse complex borderless diagrams and graphical waveforms.
3. **Semantic Staleness Gradient:** Differentiate between purely stylistic revisions (e.g. typos, rephrased sentences) and safety-critical threshold changes using automated LLM diff impact analysis.
