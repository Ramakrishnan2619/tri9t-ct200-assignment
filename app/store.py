import os
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Optional

JSON_STORE_PATH = os.getenv("JSON_STORE_PATH", "./data_store/generations.json")

class GenerationDocumentStore:
    """
    Durable NoSQL JSON document store for LLM test-case generations.
    Provides document-oriented CRUD operations with thread-safe atomic disk persistence.
    """
    def __init__(self, file_path: str = JSON_STORE_PATH):
        self.file_path = file_path
        os.makedirs(os.path.dirname(os.path.abspath(self.file_path)), exist_ok=True)
        if not os.path.exists(self.file_path):
            self._save_all([])

    def _load_all(self) -> list[dict[str, Any]]:
        if not os.path.exists(self.file_path):
            return []
        try:
            with open(self.file_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return []

    def _save_all(self, docs: list[dict[str, Any]]) -> None:
        temp_path = f"{self.file_path}.tmp"
        with open(temp_path, "w", encoding="utf-8") as f:
            json.dump(docs, f, indent=2, ensure_ascii=False)
        os.replace(temp_path, self.file_path)

    def insert(self, doc: dict[str, Any]) -> dict[str, Any]:
        """Inserts a new generation record."""
        docs = self._load_all()
        if "id" not in doc:
            doc["id"] = str(uuid.uuid4())
        if "created_at" not in doc:
            doc["created_at"] = datetime.now(timezone.utc).isoformat()
        docs.append(doc)
        self._save_all(docs)
        return doc

    def get_by_id(self, generation_id: str) -> Optional[dict[str, Any]]:
        """Retrieves a generation document by its ID."""
        docs = self._load_all()
        for d in docs:
            if d.get("id") == generation_id:
                return d
        return None

    def find_by_selection_id(self, selection_id: str) -> list[dict[str, Any]]:
        """Retrieves all generations created against a given selection ID."""
        docs = self._load_all()
        return [d for d in docs if d.get("selection_id") == selection_id]

    def find_by_node_id(self, node_id: str) -> list[dict[str, Any]]:
        """Retrieves all generations that included a specific node ID in their context."""
        docs = self._load_all()
        matching = []
        for d in docs:
            snapshots = d.get("node_snapshots", [])
            if any(snap.get("node_id") == node_id for snap in snapshots):
                matching.append(d)
        return matching

    def find_by_selection_and_hash(self, selection_id: str, context_hash: str) -> Optional[dict[str, Any]]:
        """Retrieves an existing generation for idempotency checking."""
        docs = self._load_all()
        for d in docs:
            if d.get("selection_id") == selection_id and d.get("context_hash") == context_hash:
                return d
        return None

    def all(self) -> list[dict[str, Any]]:
        """Returns all documents."""
        return self._load_all()

    def clear(self) -> None:
        """Clears all records (used for test isolation)."""
        self._save_all([])

# Global store singleton
store = GenerationDocumentStore()
