import json
import os
import uuid
from datetime import datetime
from pathlib import Path

import chromadb
from sentence_transformers import SentenceTransformer

_CHROMA_DIR = "./chroma_db"
_META_FILE  = "./kb/metadata.json"

_embed: SentenceTransformer | None = None
_col = None


def _get_embed():
    global _embed
    if _embed is None:
        _embed = SentenceTransformer("paraphrase-multilingual-MiniLM-L12-v2")
    return _embed


def _get_col():
    global _col
    if _col is None:
        client = chromadb.PersistentClient(path=_CHROMA_DIR)
        _col = client.get_or_create_collection("knowledge_base")
    return _col


def _load_meta() -> dict:
    if os.path.exists(_META_FILE):
        with open(_META_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def _save_meta(meta: dict):
    with open(_META_FILE, "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=2)


def _chunk(text: str, size=800, overlap=120) -> list[str]:
    chunks, i = [], 0
    while i < len(text):
        c = text[i : i + size]
        if len(c.strip()) > 30:
            chunks.append(c)
        i += size - overlap
    return chunks


def add_document(filename: str, text: str) -> str:
    chunks = _chunk(text)
    if not chunks:
        raise ValueError("Fayldan mətn çıxarıla bilmədi")

    doc_id     = str(uuid.uuid4())
    embeddings = _get_embed().encode(chunks).tolist()

    _get_col().add(
        ids       = [f"{doc_id}_{i}" for i in range(len(chunks))],
        embeddings= embeddings,
        documents = chunks,
        metadatas = [{"doc_id": doc_id, "filename": filename} for _ in chunks],
    )

    meta = _load_meta()
    meta[doc_id] = {
        "filename":    filename,
        "uploaded_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "chunks":      len(chunks),
    }
    _save_meta(meta)
    return doc_id


def search(query: str, n: int = 5) -> list[str]:
    col = _get_col()
    if col.count() == 0:
        return []
    embedding = _get_embed().encode([query]).tolist()
    results   = col.query(query_embeddings=embedding, n_results=min(n, col.count()))
    return results["documents"][0] if results["documents"] else []


def delete_document(doc_id: str):
    col     = _get_col()
    results = col.get(where={"doc_id": doc_id})
    if results["ids"]:
        col.delete(ids=results["ids"])
    meta = _load_meta()
    meta.pop(doc_id, None)
    _save_meta(meta)


def list_documents() -> dict:
    return _load_meta()
