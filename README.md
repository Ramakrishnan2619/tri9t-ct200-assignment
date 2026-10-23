# CardioTrack CT-200 Traceability & QA Test Generation Engine

[![Python 3.11](https://img.shields.io/badge/python-3.11-blue.svg)](https://www.python.org/downloads/)
[![FastAPI](https://img.shields.io/badge/FastAPI-0.110+-green.svg)](https://fastapi.tiangolo.com)
[![Pydantic v2](https://img.shields.io/badge/Pydantic-v2-orange.svg)](https://docs.pydantic.dev)
[![Tests Passing](https://img.shields.io/badge/tests-12%20passed-brightgreen.svg)]()

Backend system for medical device requirement traceability (**IEC 62304**). Parses technical PDF manuals into a structured, versioned hierarchy, enables version-pinned selections, generates rigorous QA test cases via LLMs, and detects stale test cases when specifications change across document versions.

---

## Architecture Overview

```
[ PDF Manual Ingestion ] ────► [ PyMuPDF / pdfplumber Extraction ]
                                            │
                                            ▼
[ Document Version Matcher ] ◄────► [ Hierarchy Tree Builder & Content Hasher ]
           │                                │
           ▼                                ▼
[ Re-ingestion & Diff Engine ]    [ SQLite Relational Store (SQLAlchemy) ]
                                            │
                                            ▼
                              [ Version-Pinned Selection API ]
                                            │
                                            ▼
                              [ LLM QA Generator with Guardrails ]
                                            │
                                            ▼
                              [ NoSQL Document Store (JSON) ]
                                            │
                                            ▼
                              [ Dynamic Staleness & Impact Engine ]
```

---

## Features

- **Document Parsing:** Reconstructs parent-child section trees, extracts markdown tables, normalizes Unicode ligatures, and computes deterministic SHA-256 content hashes.
- **Irregularity Handling:** Accurately handles duplicate headings across chapters, irregular heading font sizes, hierarchy depth skips, and out-of-order section numbering.
- **Document Versioning:** Supports re-ingesting updated manuals (`v1.0` $\to$ `v2.0`) without destroying earlier versions. Re-uses logical node IDs for unchanged sections and flags modified/added sections.
- **Version-Pinned Selections:** Selections bind directly to specific document versions and snapshot text, guaranteeing reproducibility.
- **Structured LLM Output:** Generates 3–5 repeatable QA test cases with Pydantic JSON schema enforcement, self-correction retry loops, and deterministic offline fallback.
- **Dynamic Staleness Detection:** Evaluates whether previously generated test cases reflect the active document version, flagging `CURRENT`, `STALE`, or `DELETED` with numerical parameter shift analysis.

---

## Project Structure

```
tri9t-ct200-assignment/
├── data/
│   ├── ct200_manual_v1.pdf       # CT-200 manual version 1.0
│   └── ct200_manual_v2.pdf       # CT-200 manual version 2.0 (updated specs)
├── app/
│   ├── __init__.py
│   ├── database.py               # SQLAlchemy SQLite engine & session management
│   ├── models.py                 # DocumentVersion, Node, Selection ORM models
│   ├── schemas.py                # Pydantic validation & response schemas
│   ├── parser.py                 # PDF layout-aware parser & content hasher
│   ├── versioning.py             # Version matcher & semantic diff engine
│   ├── llm.py                    # LLM QA generator with Pydantic guardrails & retries
│   ├── staleness.py              # Dynamic staleness & parameter shift analyzer
│   ├── store.py                  # Durable NoSQL JSON document repository
│   ├── ingest.py                 # Ingestion service & CLI
│   └── main.py                   # FastAPI REST API routes
├── tests/
│   ├── __init__.py
│   ├── test_parser.py            # Unit tests for PDF irregularities & hashing
│   ├── test_versioning.py        # Tests for node retention & diff classification
│   └── test_api.py               # End-to-end integration & staleness test suite
├── scripts/
│   ├── demo_workflow.py          # Complete runnable end-to-end demonstration script
│   └── inspect_manuals.py        # PDF inspection script
├── APPROACH.md                   # Approach document & Decision Log answers
├── requirements.txt              # Pinned Python dependencies
├── .env.example                  # Environment template
└── README.md
```

---

## Quickstart & Setup

### 1. Prerequisites
- Python 3.10 or 3.11
- Git

### 2. Environment Setup

```bash
# Clone the repository
git clone <your-repo-url>
cd tri9t-ct200-assignment

# Create virtual environment
python -m venv .venv

# Activate virtual environment
# On Linux/macOS:
source .venv/bin/activate
# On Windows (PowerShell):
.venv\Scripts\activate

# Install dependencies
pip install -r requirements.txt
```

### 3. Configure Environment Variables

```bash
cp .env.example .env
```

Default configuration in `.env`:
```ini
LLM_PROVIDER=mock
LLM_API_KEY=
LLM_MODEL=gemini-1.5-flash
DATABASE_URL=sqlite:///./ct200.db
JSON_STORE_PATH=./data_store/generations.json
```
*(The system runs in mock mode by default, providing realistic medical QA test cases without external API dependencies. To use live LLMs, set `LLM_PROVIDER=gemini` or `groq` and supply your `LLM_API_KEY`)*.

---

## Running the Application

### 1. Start the FastAPI Server

```bash
uvicorn app.main:app --reload --port 8000
```
- Interactive Swagger UI: [http://localhost:8000/docs](http://localhost:8000/docs)
- OpenAPI Specification: [http://localhost:8000/openapi.json](http://localhost:8000/openapi.json)

---

## Triggering the V1 $\to$ V2 Re-Ingestion Flow

### Option A: Using the CLI

```bash
# Ingest Version 1.0 (Baseline)
python -m app.ingest --file data/ct200_manual_v1.pdf --version 1.0

# Re-ingest Version 2.0 (Updates active version, detects modified/added nodes)
python -m app.ingest --file data/ct200_manual_v2.pdf --version 2.0
```

### Option B: Using the REST API

```bash
# Ingest Version 1.0
curl -X POST "http://localhost:8000/api/v1/ingest?file_path=data/ct200_manual_v1.pdf&version_label=1.0"

# Ingest Version 2.0
curl -X POST "http://localhost:8000/api/v1/ingest?file_path=data/ct200_manual_v2.pdf&version_label=2.0"
```

---

## Running Tests

Run the complete 12-test automated suite covering PDF irregularities, versioning diffs, and end-to-end staleness flow:

```bash
pytest tests/ -v
```

---

## End-to-End Demonstration Script

To run the complete automated demonstration showing:
1. Ingesting v1.0
2. Browsing top sections
3. Creating a version-pinned selection
4. Generating test cases (`CURRENT`)
5. Re-ingesting v2.0
6. Observing dynamic transition to `STALE` with detailed reason logs:

```bash
python scripts/demo_workflow.py
```

---

## Key API Endpoints Reference

| Method | Endpoint | Description |
| :--- | :--- | :--- |
| `GET` | `/api/v1/versions` | List all document versions and see active version |
| `POST` | `/api/v1/ingest` | Ingest a PDF manual as a document version |
| `GET` | `/api/v1/sections` | List top-level chapters (`version=1.0` or `latest`) |
| `GET` | `/api/v1/nodes` | Search across headings and body text |
| `GET` | `/api/v1/nodes/{id}` | Get node details, children, text, and SHA-256 hash |
| `GET` | `/api/v1/nodes/{id}/diff` | View node change status (`UNCHANGED`, `MODIFIED`, etc.) |
| `POST` | `/api/v1/selections` | Create a version-pinned selection of node IDs |
| `GET` | `/api/v1/selections/{id}` | View selection and its pinned node snapshots |
| `POST` | `/api/v1/generations` | Generate QA test cases from selection via LLM |
| `GET` | `/api/v1/generations/{id}` | Retrieve generation with dynamic staleness status |
| `GET` | `/api/v1/generations/by-selection/{id}` | Retrieve all test sets for a selection |
| `GET` | `/api/v1/generations/by-node/{node_id}` | Retrieve test cases generated from a specific node |
