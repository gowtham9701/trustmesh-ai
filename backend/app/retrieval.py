"""Local retrievers with optional persisted FAISS and cross-encoder ranking."""
from __future__ import annotations

import hashlib
import json
import math
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol


@dataclass(frozen=True)
class RetrievedDocument:
    page_content: str
    metadata: dict[str, Any]

    def to_langchain_document(self):
        """Convert to LangChain's Document only when the optional package exists."""
        try:
            from langchain_core.documents import Document
        except ImportError as exc:
            raise RuntimeError("Install langchain-core to use LangChain Document adapters") from exc
        metadata = {k: v for k, v in self.metadata.items() if k != "_chunk"}
        return Document(page_content=self.page_content, metadata=metadata)


class Retriever(Protocol):
    mode: str

    def get_relevant_documents(
        self, query: str, top_k: int = 6, tenant_id: str = "default"
    ) -> list[RetrievedDocument]: ...


class StoreRetriever:
    def __init__(self, store: Any, mode: str | None = None):
        self.store = store
        self.requested_mode = (mode or os.getenv("RETRIEVAL_MODE", "auto")).lower()
        self.mode = "deterministic"
        self.fallback_reason: str | None = None
        self.reranker = "disabled"
        if self.requested_mode == "semantic":
            if self._semantic_available():
                self.mode = "semantic"
            else:
                self.fallback_reason = "sentence-transformers and faiss-cpu are not installed"
        elif self.requested_mode not in {"auto", "deterministic"}:
            self.fallback_reason = f"unknown retrieval mode: {self.requested_mode}"

    @staticmethod
    def _semantic_available() -> bool:
        try:
            import faiss  # noqa: F401
            import sentence_transformers  # noqa: F401
        except ImportError:
            return False
        return True

    def _semantic_search(self, query: str, top_k: int, tenant_id: str):
        import faiss
        import numpy as np
        from sentence_transformers import SentenceTransformer

        if os.getenv("MODEL_DOWNLOADS_ALLOWED", "false").lower() not in {"true", "1", "yes"}:
            os.environ.setdefault("HF_HUB_OFFLINE", "1")
        chunks = self.store.get_chunks(tenant_id)
        if not chunks:
            return []
        model_name = os.getenv("EMBEDDING_MODEL", "sentence-transformers/all-MiniLM-L6-v2")
        model = SentenceTransformer(model_name)
        cache_root = Path(os.getenv("VECTOR_INDEX_DIR", str(self.store.data_dir / "vector-index")))
        cache_root.mkdir(parents=True, exist_ok=True)
        os.chmod(cache_root, 0o700)
        fingerprint_src = tenant_id + model_name + "".join(
            f"{c.chunk_id}:{hashlib.sha256(c.text.encode()).hexdigest()}" for c in chunks
        )
        fingerprint = hashlib.sha256(fingerprint_src.encode()).hexdigest()
        index_path = cache_root / f"{fingerprint}.faiss"
        metadata_path = cache_root / f"{fingerprint}.json"
        if index_path.exists() and metadata_path.exists():
            encoded_index = self.store.decrypt_bytes(index_path.read_bytes())
            index = faiss.deserialize_index(np.frombuffer(encoded_index, dtype="uint8"))
            chunk_ids = json.loads(metadata_path.read_text(encoding="utf-8"))
            by_id = {chunk.chunk_id: chunk for chunk in chunks}
            ordered_chunks = [by_id[chunk_id] for chunk_id in chunk_ids if chunk_id in by_id]
        else:
            vectors = model.encode(
                [chunk.text for chunk in chunks], normalize_embeddings=True, convert_to_numpy=True
            ).astype("float32")
            index = faiss.IndexFlatIP(vectors.shape[1])
            index.add(vectors)
            self._atomic_write(
                index_path,
                self.store.encrypt_bytes(faiss.serialize_index(index).tobytes()),
            )
            self._atomic_write(
                metadata_path,
                json.dumps([chunk.chunk_id for chunk in chunks]).encode("utf-8"),
            )
            ordered_chunks = chunks
        query_vector = model.encode(
            [query], normalize_embeddings=True, convert_to_numpy=True
        ).astype("float32")
        scores, positions = index.search(query_vector, min(top_k, len(ordered_chunks)))
        return [
            (ordered_chunks[position], max(0.0, float(score)))
            for score, position in zip(scores[0], positions[0])
            if 0 <= position < len(ordered_chunks)
        ]

    @staticmethod
    def _atomic_write(path: Path, content: bytes) -> None:
        temporary_path = None
        try:
            with tempfile.NamedTemporaryFile(dir=path.parent, delete=False) as temporary:
                temporary_path = Path(temporary.name)
                temporary.write(content)
                temporary.flush()
                os.fsync(temporary.fileno())
            os.chmod(temporary_path, 0o600)
            os.replace(temporary_path, path)
        finally:
            if temporary_path is not None and temporary_path.exists():
                temporary_path.unlink()

    def _rerank(self, query: str, hits: list[tuple[Any, float]]) -> list[tuple[Any, float]]:
        if os.getenv("RERANKER_ENABLED", "false").lower() not in {"true", "1", "yes"} or not hits:
            return hits
        try:
            from sentence_transformers import CrossEncoder
            if os.getenv("MODEL_DOWNLOADS_ALLOWED", "false").lower() not in {"true", "1", "yes"}:
                os.environ.setdefault("HF_HUB_OFFLINE", "1")
            reranker = CrossEncoder(os.getenv(
                "RERANKER_MODEL", "cross-encoder/ms-marco-MiniLM-L-6-v2"
            ))
            scores = reranker.predict([(query, chunk.text) for chunk, _ in hits])
            self.reranker = "cross-encoder"
            return sorted(
                [
                    (chunk, 1 / (1 + math.exp(-max(-30.0, min(30.0, float(score))))))
                    for (chunk, _), score in zip(hits, scores)
                ],
                key=lambda item: item[1],
                reverse=True,
            )
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self.reranker = f"fallback ({type(exc).__name__})"
            return hits

    def get_relevant_documents(
        self, query: str, top_k: int = 6, tenant_id: str = "default"
    ) -> list[RetrievedDocument]:
        if self.requested_mode == "auto" and os.getenv(
            "BANDIT_ROUTING_ENABLED", "false"
        ).lower() in {"true", "1", "yes"} and self._semantic_available():
            self.mode = self.store.choose_retrieval_route(
                tenant_id,
                self.store._query_context(query),
                ["deterministic", "semantic"],
            )
        try:
            hits = (
                self._semantic_search(query, top_k, tenant_id)
                if self.mode == "semantic"
                else self.store.search(query, top_k, tenant_id)
            )
        except (ImportError, OSError, RuntimeError, ValueError) as exc:
            self.mode = "deterministic"
            self.fallback_reason = f"semantic retrieval unavailable: {type(exc).__name__}"
            hits = self.store.search(query, top_k, tenant_id)
        hits = self._rerank(query, hits)
        return [
            RetrievedDocument(
                page_content=chunk.text,
                metadata={
                    "document_id": chunk.document_id,
                    "filename": chunk.filename,
                    "chunk_id": chunk.chunk_id,
                    "score": score,
                    "_chunk": chunk,
                },
            )
            for chunk, score in hits
        ]


def retrieval_metadata(store: Any) -> dict[str, Any]:
    retriever = StoreRetriever(store)
    return {
        "requested_mode": retriever.requested_mode,
        "mode": retriever.mode,
        "semantic_available": retriever._semantic_available(),
        "fallback_reason": retriever.fallback_reason,
        "reranker_enabled": os.getenv("RERANKER_ENABLED", "false").lower() in {"true", "1", "yes"},
        "feedback_bandit_enabled": os.getenv("BANDIT_ROUTING_ENABLED", "false").lower()
        in {"true", "1", "yes"},
        "vector_index_dir": os.getenv("VECTOR_INDEX_DIR", str(store.data_dir / "vector-index")),
        "optional_dependencies": ["sentence-transformers", "faiss-cpu", "langchain-core"],
    }
