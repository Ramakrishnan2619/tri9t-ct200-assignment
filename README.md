# CT-200 Traceability & LLM Test Case Pipeline

FastAPI backend for parsing medical device PDF manuals, tracking document versions, and generating traceable QA test cases with automatic staleness detection.

---

## Project Structure

```text
tri9t-ct200-assignment/
├── data/
│   ├── ct200_manual_v1.pdf
│   └── ct200_manual_v2.pdf
├── app/
│   ├── __init__.py
│   ├── main.py
│   ├── database.py
│   ├── models.py
│   ├── schemas.py
│   ├── parser.py
│   ├── versioning.py
│   ├── llm.py
│   ├── staleness.py
│   ├── store.py
│   └── ingest.py
├── tests/
│   └── test_pipeline.py
├── .env.example
├── .gitignore
├── requirements.txt
├── README.md
└── APPROACH.md
```

---

## Quickstart

### 1. Install Dependencies

```bash
# Create and activate virtual environment
python -m venv .venv

# On Windows:
.venv\Scripts\activate
# On Linux / macOS:
source .venv/bin/activate

# Install required packages
pip install -r requirements.txt
```

### 2. Configure Environment

Copy `.env.example` to `.env`:

```bash
cp .env.example .env
```

*(By default, `LLM_PROVIDER=mock` runs locally without requiring external API keys. You can set `LLM_PROVIDER=gemini` or `groq` and supply an API key in `.env` if you want live calls).*

### 3. Run the API Server

```bash
uvicorn app.main:app --reload --port 8000
```

Once running, you can explore the interactive API documentation at:
- **Swagger UI:** [http://localhost:8000/docs](http://localhost:8000/docs)

---

## How to Trigger the V1 $\to$ V2 Re-Ingestion Flow

### Using the Ingestion CLI:

```bash
# 1. Ingest baseline manual (Version 1.0)
python -m app.ingest --file data/ct200_manual_v1.pdf --version 1.0

# 2. Re-ingest modified manual (Version 2.0)
python -m app.ingest --file data/ct200_manual_v2.pdf --version 2.0
```

### Or using the REST API:

```bash
# Ingest v1.0
curl -X POST "http://localhost:8000/api/v1/ingest?file_path=data/ct200_manual_v1.pdf&version_label=1.0"

# Re-ingest v2.0
curl -X POST "http://localhost:8000/api/v1/ingest?file_path=data/ct200_manual_v2.pdf&version_label=2.0"
```

---

## Running the Automated Test Suite

Run pytest to execute the pipeline test suite covering PDF hierarchy extraction, irregular headings, version diffs, selections, and staleness detection:

```bash
pytest tests/ -v
```

---

## API Endpoints

- `GET /api/v1/versions`: List all ingested versions and see active version
- `POST /api/v1/ingest`: Trigger ingestion of a manual version
- `GET /api/v1/sections`: List top-level chapters (`version=1.0` or `latest`)
- `GET /api/v1/nodes`: Search nodes by keyword or filter by level
- `GET /api/v1/nodes/{id}`: Get node text, children, path, and SHA-256 hash
- `GET /api/v1/nodes/{id}/diff`: View whether node changed across versions and diff summary
- `POST /api/v1/selections`: Create a version-pinned selection of node IDs
- `GET /api/v1/selections/{id}`: View selection details
- `POST /api/v1/generations`: Generate QA test cases from selection
- `GET /api/v1/generations/{id}`: Retrieve test cases with active staleness status (`CURRENT` / `STALE`)
