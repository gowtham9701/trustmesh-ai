from __future__ import annotations

import hashlib
import json
import os
import re
import sqlite3
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CHUNK_MAX_CHARS = 4000
CHUNK_TARGET_CHARS = 1200


def _split_windows(paragraph: str) -> list[str]:
    """Break an oversized paragraph into sentence-aligned retrieval windows.

    Evidence without blank lines - pretty-printed JSON, minified logs, one long
    prose paragraph - would otherwise become a single chunk. Claim extraction
    works per sentence inside a chunk, so a single oversized chunk yields only
    tiny fragments (one JSON key per line) and no answer claim can clear the
    term-overlap threshold.
    """
    if len(paragraph) <= CHUNK_TARGET_CHARS:
        return [paragraph]
    windows: list[str] = []
    current = ""
    for sentence in re.split(r"(?<=[.!?])\s+|\n+", paragraph):
        sentence = sentence.strip()
        if not sentence:
            continue
        if len(sentence) > CHUNK_MAX_CHARS:
            if current:
                windows.append(current)
                current = ""
            windows.extend(
                sentence[offset:offset + CHUNK_MAX_CHARS]
                for offset in range(0, len(sentence), CHUNK_MAX_CHARS)
            )
            continue
        if current and len(current) + len(sentence) + 1 > CHUNK_TARGET_CHARS:
            windows.append(current)
            current = sentence
        else:
            current = f"{current} {sentence}" if current else sentence
    if current:
        windows.append(current)
    return windows or [paragraph]


def _split_parts(text: str) -> list[str]:
    paragraphs = [part.strip() for part in re.split(r"\n\s*\n", text) if part.strip()]
    if not paragraphs:
        paragraphs = [text.strip()]
    parts: list[str] = []
    for paragraph in paragraphs:
        parts.extend(_split_windows(paragraph))
    return parts


@dataclass
class Chunk:
    document_id: str
    filename: str
    chunk_id: str
    text: str
    tenant_id: str = "default"
    version: int = 1


class Store:
    """SQLite-backed evidence and feedback store with tenant-scoped document versions."""

    def __init__(self, data_dir: str | Path = "data", database_path: str | Path | None = None):
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.database_path = Path(database_path or os.getenv(
            "DATABASE_PATH", str(self.data_dir / "trustmesh.sqlite3")
        ))
        self.database_path.parent.mkdir(parents=True, exist_ok=True)
        self._initialize()
        self._apply_retention()
        self._load_demo()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        for path in (
            self.database_path,
            Path(f"{self.database_path}-wal"),
            Path(f"{self.database_path}-shm"),
        ):
            if path.exists():
                os.chmod(path, 0o600)
        return connection

    def _initialize(self) -> None:
        with self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS documents (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    content_type TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    version INTEGER NOT NULL,
                    characters INTEGER NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    UNIQUE(tenant_id, filename, version)
                );
                CREATE INDEX IF NOT EXISTS documents_tenant_idx ON documents(tenant_id);
                CREATE TABLE IF NOT EXISTS chunks (
                    id TEXT PRIMARY KEY,
                    document_id TEXT NOT NULL REFERENCES documents(id) ON DELETE CASCADE,
                    tenant_id TEXT NOT NULL,
                    filename TEXT NOT NULL,
                    text TEXT NOT NULL,
                    FOREIGN KEY(document_id) REFERENCES documents(id)
                );
                CREATE INDEX IF NOT EXISTS chunks_tenant_idx ON chunks(tenant_id);
                CREATE TABLE IF NOT EXISTS investigations (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS investigations_tenant_idx ON investigations(tenant_id);
                CREATE TABLE IF NOT EXISTS feedback (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    investigation_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    rating TEXT NOT NULL,
                    comment TEXT NOT NULL,
                    retrieval_mode TEXT NOT NULL DEFAULT 'deterministic',
                    context TEXT NOT NULL DEFAULT 'general',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS feedback_tenant_idx ON feedback(tenant_id);
                CREATE TABLE IF NOT EXISTS audit_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tenant_id TEXT NOT NULL,
                    actor TEXT NOT NULL,
                    action TEXT NOT NULL,
                    resource_id TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE INDEX IF NOT EXISTS audit_tenant_idx ON audit_events(tenant_id);
                CREATE TABLE IF NOT EXISTS route_feedback (
                    tenant_id TEXT NOT NULL,
                    route TEXT NOT NULL,
                    positive INTEGER NOT NULL DEFAULT 0,
                    negative INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(tenant_id, route)
                );
                CREATE TABLE IF NOT EXISTS contextual_route_feedback (
                    tenant_id TEXT NOT NULL,
                    context TEXT NOT NULL,
                    route TEXT NOT NULL,
                    positive INTEGER NOT NULL DEFAULT 0,
                    negative INTEGER NOT NULL DEFAULT 0,
                    PRIMARY KEY(tenant_id, context, route)
                );
                CREATE TABLE IF NOT EXISTS evaluation_runs (
                    id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    payload TEXT NOT NULL,
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                );
                CREATE TABLE IF NOT EXISTS approvals (
                    id TEXT PRIMARY KEY,
                    investigation_id TEXT NOT NULL,
                    tenant_id TEXT NOT NULL,
                    action TEXT NOT NULL,
                    rationale TEXT NOT NULL,
                    status TEXT NOT NULL,
                    requested_by TEXT NOT NULL,
                    decided_by TEXT,
                    decision_comment TEXT NOT NULL DEFAULT '',
                    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
                    decided_at TEXT
                );
                CREATE INDEX IF NOT EXISTS approvals_tenant_idx ON approvals(tenant_id,status);
                """
            )
            feedback_columns = {
                row["name"] for row in connection.execute("PRAGMA table_info(feedback)")
            }
            if "retrieval_mode" not in feedback_columns:
                connection.execute(
                    "ALTER TABLE feedback ADD COLUMN retrieval_mode TEXT NOT NULL DEFAULT 'deterministic'"
                )
            if "context" not in feedback_columns:
                connection.execute(
                    "ALTER TABLE feedback ADD COLUMN context TEXT NOT NULL DEFAULT 'general'"
                )

    def _apply_retention(self) -> None:
        retention_days = int(os.getenv("RETENTION_DAYS", "0"))
        if retention_days <= 0:
            return
        with self._connect() as connection:
            connection.execute(
                "DELETE FROM documents WHERE created_at < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            connection.execute(
                "DELETE FROM investigations WHERE created_at < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            connection.execute(
                "DELETE FROM feedback WHERE created_at < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            connection.execute(
                "DELETE FROM evaluation_runs WHERE created_at < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            connection.execute(
                """DELETE FROM approvals WHERE status != 'pending'
                   AND created_at < datetime('now', ?)""", (f"-{retention_days} days",)
            )
            connection.execute(
                "DELETE FROM audit_events WHERE created_at < datetime('now', ?)",
                (f"-{retention_days} days",),
            )
            connection.execute("DELETE FROM route_feedback")
            connection.execute(
                """INSERT INTO route_feedback(tenant_id,route,positive,negative)
                   SELECT tenant_id,retrieval_mode,
                   SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN rating='not_helpful' THEN 1 ELSE 0 END)
                   FROM feedback GROUP BY tenant_id,retrieval_mode"""
            )
            connection.execute("DELETE FROM contextual_route_feedback")
            connection.execute(
                """INSERT INTO contextual_route_feedback(tenant_id,context,route,positive,negative)
                   SELECT tenant_id,context,retrieval_mode,
                   SUM(CASE WHEN rating='helpful' THEN 1 ELSE 0 END),
                   SUM(CASE WHEN rating='not_helpful' THEN 1 ELSE 0 END)
                   FROM feedback GROUP BY tenant_id,context,retrieval_mode"""
            )

    def _load_demo(self) -> None:
        demo = self.data_dir / "synthetic_incidents.json"
        if demo.exists():
            self.ingest_bytes(demo.name, demo.read_bytes(), "application/json", "default")

    @staticmethod
    def _fernet():
        key = os.getenv("DATA_ENCRYPTION_KEY")
        if not key:
            return None
        try:
            from cryptography.fernet import Fernet
            return Fernet(key.encode())
        except (ImportError, ValueError) as exc:
            raise RuntimeError("DATA_ENCRYPTION_KEY must be a valid Fernet key; install cryptography") from exc

    def _encode_text(self, text: str) -> str:
        encoded = self.encrypt_bytes(text.encode())
        return encoded.decode()

    def _decode_text(self, text: str) -> str:
        return self.decrypt_bytes(text.encode()).decode()

    def encrypt_bytes(self, payload: bytes) -> bytes:
        cipher = self._fernet()
        if cipher is None:
            return payload
        return b"fernet:" + cipher.encrypt(payload)

    def decrypt_bytes(self, payload: bytes) -> bytes:
        if not payload.startswith(b"fernet:"):
            return payload
        cipher = self._fernet()
        if cipher is None:
            raise RuntimeError("Encrypted content requires DATA_ENCRYPTION_KEY")
        return cipher.decrypt(payload.removeprefix(b"fernet:"))

    def ingest_bytes(
        self,
        filename: str,
        raw: bytes,
        content_type: str = "",
        tenant_id: str = "default",
        actor: str = "system",
    ) -> dict[str, Any]:
        filename = Path(filename).name
        ext = Path(filename).suffix.lower()
        if ext not in {".md", ".txt", ".json"}:
            raise ValueError("Only .md, .txt, and .json files are supported")
        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError("File must be UTF-8 text") from exc
        if ext == ".json":
            try:
                text = json.dumps(json.loads(text), indent=2, ensure_ascii=False)
            except json.JSONDecodeError as exc:
                raise ValueError("Invalid JSON document") from exc
        if not text.strip():
            raise ValueError("Document is empty")
        if len(raw) > int(os.getenv("MAX_UPLOAD_BYTES", str(10 * 1024 * 1024))):
            raise ValueError("Document exceeds MAX_UPLOAD_BYTES")

        digest = hashlib.sha256(raw).hexdigest()
        parts = _split_parts(text)
        with self._connect() as connection:
            connection.execute("BEGIN IMMEDIATE")
            existing_row = connection.execute(
                """SELECT id,tenant_id,filename,content_type,version,characters,content_hash
                   FROM documents WHERE tenant_id=? AND filename=? AND content_hash=?""",
                (tenant_id, filename, digest),
            ).fetchone()
            if existing_row:
                existing_chunks = connection.execute(
                    "SELECT COUNT(*) FROM chunks WHERE document_id=?", (existing_row["id"],)
                ).fetchone()[0]
                existing = {
                    **dict(existing_row), "chunks": existing_chunks,
                }
                return existing
            version = connection.execute(
                "SELECT COALESCE(MAX(version),0)+1 FROM documents WHERE tenant_id=? AND filename=?",
                (tenant_id, filename),
            ).fetchone()[0]
            doc_id = uuid.uuid4().hex[:12]
            chunks = [
                Chunk(doc_id, filename, f"{doc_id}-{i + 1}", p[:CHUNK_MAX_CHARS], tenant_id, version)
                for i, p in enumerate(parts)
            ]
            metadata = {
                "id": doc_id, "tenant_id": tenant_id, "filename": filename,
                "content_type": content_type or "text/plain", "chunks": len(chunks),
                "characters": len(text), "version": version, "content_hash": digest,
            }
            connection.execute(
                """INSERT INTO documents(id,tenant_id,filename,content_type,content_hash,version,characters)
                   VALUES(?,?,?,?,?,?,?)""",
                (doc_id, tenant_id, filename, metadata["content_type"], digest, version, len(text)),
            )
            connection.executemany(
                "INSERT INTO chunks(id,document_id,tenant_id,filename,text) VALUES(?,?,?,?,?)",
                [(c.chunk_id, doc_id, tenant_id, filename, self._encode_text(c.text)) for c in chunks],
            )
            connection.execute(
                "INSERT INTO audit_events(tenant_id,actor,action,resource_id) VALUES(?,?,?,?)",
                (tenant_id, actor, "document.ingest", doc_id),
            )
        return metadata

    def list_documents(
        self, tenant_id: str = "default", limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT d.id,d.tenant_id,d.filename,d.content_type,d.version,d.characters,
                   COUNT(c.id) AS chunks FROM documents d LEFT JOIN chunks c ON c.document_id=d.id
                   WHERE d.tenant_id=? GROUP BY d.id ORDER BY d.created_at,d.rowid
                   LIMIT ? OFFSET ?""",
                (tenant_id, limit, offset),
            ).fetchall()
        return [dict(row) for row in rows]

    def document_count(self, tenant_id: str = "default") -> int:
        with self._connect() as connection:
            return connection.execute(
                "SELECT COUNT(*) FROM documents WHERE tenant_id=?", (tenant_id,)
            ).fetchone()[0]

    def search(self, query: str, top_k: int = 6, tenant_id: str = "default") -> list[tuple[Chunk, float]]:
        stopwords = {
            "what", "why", "how", "is", "the", "a", "an", "of", "to", "and", "for",
            "in", "on", "did", "do", "we", "should", "can", "could", "would", "likely",
            "next", "take", "action", "after", "this", "that", "with",
        }
        terms = set(re.findall(r"[a-z0-9_'-]+", query.lower())) - stopwords
        if not terms:
            return []
        scored = []
        for chunk in self.get_chunks(tenant_id):
            words = set(re.findall(r"[a-z0-9_'-]+", chunk.text.lower()))
            overlap = len(terms & words)
            if overlap:
                score = overlap / (len(terms) ** 0.5) + 0.05 * sum(
                    1 for term in terms if term in chunk.text.lower()
                )
                scored.append((chunk, round(score, 4)))
        return sorted(scored, key=lambda item: (-item[1], item[0].chunk_id))[:top_k]

    def get_chunks(self, tenant_id: str = "default") -> list[Chunk]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT c.document_id,c.filename,c.id,c.text,c.tenant_id,d.version
                   FROM chunks c JOIN documents d ON d.id=c.document_id
                   WHERE c.tenant_id=? ORDER BY c.rowid""", (tenant_id,)
            ).fetchall()
        return [
            Chunk(
                document_id=row["document_id"], filename=row["filename"], chunk_id=row["id"],
                text=self._decode_text(row["text"]), tenant_id=row["tenant_id"], version=row["version"],
            )
            for row in rows
        ]

    def save_investigation(
        self, payload: dict[str, Any], tenant_id: str = "default", actor: str = "system"
    ) -> None:
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO investigations(id,tenant_id,payload) VALUES(?,?,?)",
                (payload["investigation_id"], tenant_id, self._encode_text(json.dumps(payload))),
            )
            connection.execute(
                "INSERT INTO audit_events(tenant_id,actor,action,resource_id) VALUES(?,?,?,?)",
                (tenant_id, actor, "investigation.run", payload["investigation_id"]),
            )

    def get_investigation(self, investigation_id: str, tenant_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT payload FROM investigations WHERE id=? AND tenant_id=?",
                (investigation_id, tenant_id),
            ).fetchone()
        return json.loads(self._decode_text(row["payload"])) if row else None

    def list_feedback(self, tenant_id: str = "default") -> dict[str, Any]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT investigation_id, rating, comment, created_at FROM feedback
                   WHERE tenant_id = ? ORDER BY id""", (tenant_id,)
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            item["comment"] = self._decode_text(item["comment"])
        return {"count": len(items), "items": items}

    def add_feedback(self, entry: dict[str, Any], tenant_id: str = "default") -> dict[str, Any]:
        investigation = self.get_investigation(entry["investigation_id"], tenant_id) or {}
        context = self._query_context(investigation.get("question", ""))
        route = entry.get("retrieval_mode", "deterministic")
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO feedback(investigation_id,tenant_id,rating,comment,retrieval_mode,context)
                   VALUES(?,?,?,?,?,?)""",
                (
                    entry["investigation_id"], tenant_id, entry["rating"],
                    self._encode_text(entry["comment"]), route, context,
                ),
            )
            positive = 1 if entry["rating"] == "helpful" else 0
            negative = 1 if entry["rating"] == "not_helpful" else 0
            connection.execute(
                """INSERT INTO route_feedback(tenant_id,route,positive,negative) VALUES(?,?,?,?)
                   ON CONFLICT(tenant_id,route) DO UPDATE SET
                   positive=positive+excluded.positive, negative=negative+excluded.negative""",
                (tenant_id, route, positive, negative),
            )
            connection.execute(
                """INSERT INTO contextual_route_feedback(tenant_id,context,route,positive,negative)
                   VALUES(?,?,?,?,?) ON CONFLICT(tenant_id,context,route) DO UPDATE SET
                   positive=positive+excluded.positive,negative=negative+excluded.negative""",
                (tenant_id, context, route, positive, negative),
            )
            connection.execute(
                "INSERT INTO audit_events(tenant_id,actor,action,resource_id) VALUES(?,?,?,?)",
                (tenant_id, entry.get("actor", "user"), "feedback.submit", entry["investigation_id"]),
            )
        return entry

    def feedback_metrics(self, tenant_id: str = "default") -> dict[str, Any]:
        with self._connect() as connection:
            counts = connection.execute(
                """SELECT route, positive, negative FROM route_feedback
                   WHERE tenant_id = ? ORDER BY route""", (tenant_id,)
            ).fetchall()
            total = connection.execute(
                "SELECT COUNT(*) FROM feedback WHERE tenant_id = ?", (tenant_id,)
            ).fetchone()[0]
            contextual = connection.execute(
                """SELECT context,route,positive,negative FROM contextual_route_feedback
                   WHERE tenant_id=? ORDER BY context,route""", (tenant_id,)
            ).fetchall()
        return {
            "feedback_count": total,
            "routes": [
                {"route": row["route"], "positive": row["positive"], "negative": row["negative"],
                 "positive_rate": round(row["positive"] / max(1, row["positive"] + row["negative"]), 3)}
                for row in counts
            ],
            "contextual_routes": [
                {"context": row["context"], "route": row["route"], "positive": row["positive"],
                 "negative": row["negative"]}
                for row in contextual
            ],
        }

    @staticmethod
    def _query_context(question: str) -> str:
        value = question.lower()
        categories = {
            "security": ("credential", "secret", "security", "breach", "exposure"),
            "latency": ("latency", "slow", "timeout", "response time"),
            "capacity": ("capacity", "queue", "worker", "saturation", "backlog"),
            "availability": ("outage", "unavailable", "error", "5xx", "down"),
        }
        for context, terms in categories.items():
            if any(term in value for term in terms):
                return context
        return "general"

    def choose_retrieval_route(self, tenant_id: str, context: str, routes: list[str]) -> str:
        if not routes:
            return "deterministic"
        with self._connect() as connection:
            observations = connection.execute(
                """SELECT route,positive,negative FROM contextual_route_feedback
                   WHERE tenant_id=? AND context=?""", (tenant_id, context)
            ).fetchall()
        stats = {row["route"]: (row["positive"], row["negative"]) for row in observations}
        total = sum(pos + neg for pos, neg in stats.values())
        for route in sorted(routes):
            if route not in stats or sum(stats[route]) == 0:
                return route
        import math
        return max(
            routes,
            key=lambda route: (
                stats[route][0] / max(1, sum(stats[route]))
                + math.sqrt(2 * math.log(max(2, total)) / max(1, sum(stats[route]))),
                route,
            ),
        )

    def audit_events(self, tenant_id: str = "default", limit: int = 100) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                """SELECT actor,action,resource_id,created_at FROM audit_events
                   WHERE tenant_id = ? ORDER BY id DESC LIMIT ?""", (tenant_id, limit)
            ).fetchall()
        return [dict(row) for row in rows]

    def save_evaluation(
        self, result: dict[str, Any], tenant_id: str = "default", actor: str = "system"
    ) -> str:
        run_id = uuid.uuid4().hex[:12]
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO evaluation_runs(id,tenant_id,payload) VALUES(?,?,?)",
                (run_id, tenant_id, self._encode_text(json.dumps(result))),
            )
            connection.execute(
                "INSERT INTO audit_events(tenant_id,actor,action,resource_id) VALUES(?,?,?,?)",
                (tenant_id, actor, "evaluation.run", run_id),
            )
        return run_id

    def latest_evaluation(self, tenant_id: str = "default") -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                """SELECT id,payload,created_at FROM evaluation_runs
                   WHERE tenant_id = ? ORDER BY created_at DESC,rowid DESC LIMIT 1""",
                (tenant_id,),
            ).fetchone()
        if row is None:
            return None
        return {
            "run_id": row["id"], "created_at": row["created_at"],
            **json.loads(self._decode_text(row["payload"])),
        }

    def create_approval(
        self, investigation_id: str, tenant_id: str, action: str, rationale: str, requested_by: str
    ) -> dict[str, Any]:
        approval_id = uuid.uuid4().hex[:12]
        with self._connect() as connection:
            connection.execute(
                """INSERT INTO approvals(id,investigation_id,tenant_id,action,rationale,status,requested_by)
                   VALUES(?,?,?,?,?,'pending',?)""",
                (
                    approval_id, investigation_id, tenant_id, self._encode_text(action),
                    self._encode_text(rationale), requested_by,
                ),
            )
            connection.execute(
                "INSERT INTO audit_events(tenant_id,actor,action,resource_id) VALUES(?,?,?,?)",
                (tenant_id, requested_by, "approval.request", approval_id),
            )
        approval = self.get_approval(approval_id, tenant_id)
        if approval is None:
            raise RuntimeError("Approval request could not be persisted")
        return approval

    def get_approval(self, approval_id: str, tenant_id: str) -> dict[str, Any] | None:
        with self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM approvals WHERE id=? AND tenant_id=?", (approval_id, tenant_id)
            ).fetchone()
        if row is None:
            return None
        result = dict(row)
        for field in ("action", "rationale", "decision_comment"):
            result[field] = self._decode_text(result[field])
        return result

    def list_approvals(self, tenant_id: str) -> list[dict[str, Any]]:
        with self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM approvals WHERE tenant_id=? ORDER BY created_at DESC", (tenant_id,)
            ).fetchall()
        items = [dict(row) for row in rows]
        for item in items:
            for field in ("action", "rationale", "decision_comment"):
                item[field] = self._decode_text(item[field])
        return items

    def decide_approval(
        self, approval_id: str, tenant_id: str, decision: str, comment: str, decided_by: str
    ) -> dict[str, Any] | None:
        with self._connect() as connection:
            cursor = connection.execute(
                """UPDATE approvals SET status=?,decision_comment=?,decided_by=?,decided_at=CURRENT_TIMESTAMP
                   WHERE id=? AND tenant_id=? AND status='pending'""",
                (decision, self._encode_text(comment), decided_by, approval_id, tenant_id),
            )
            if cursor.rowcount:
                connection.execute(
                    "INSERT INTO audit_events(tenant_id,actor,action,resource_id) VALUES(?,?,?,?)",
                    (tenant_id, decided_by, f"approval.{decision}", approval_id),
                )
        return self.get_approval(approval_id, tenant_id)
