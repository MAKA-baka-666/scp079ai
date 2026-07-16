"""Persistent long-term memory backed by SQLite + FTS5."""

import json
import os
import sqlite3
import time
from datetime import datetime
from threading import Lock


class PersistentMemory:
    """SQLite-backed memory store with full-text search."""

    def __init__(self, db_path: str):
        os.makedirs(os.path.dirname(db_path) or ".", exist_ok=True)
        self.db_path = db_path
        self._lock = Lock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_path)
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_db(self) -> None:
        with self._lock:
            conn = self._connect()
            conn.executescript("""
                CREATE TABLE IF NOT EXISTS memories (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    importance REAL DEFAULT 0.5,
                    created_at TEXT DEFAULT (datetime('now')),
                    last_accessed_at TEXT DEFAULT (datetime('now')),
                    access_count INTEGER DEFAULT 0,
                    tags TEXT DEFAULT '[]',
                    source TEXT DEFAULT 'conversation'
                );

                CREATE VIRTUAL TABLE IF NOT EXISTS memories_fts USING fts5(
                    content, content='memories', content_rowid='id'
                );

                CREATE TRIGGER IF NOT EXISTS memories_ai AFTER INSERT ON memories BEGIN
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_ad AFTER DELETE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                END;

                CREATE TRIGGER IF NOT EXISTS memories_au AFTER UPDATE ON memories BEGIN
                    INSERT INTO memories_fts(memories_fts, rowid, content)
                    VALUES ('delete', old.id, old.content);
                    INSERT INTO memories_fts(rowid, content) VALUES (new.id, new.content);
                END;

                CREATE TABLE IF NOT EXISTS sessions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    started_at TEXT DEFAULT (datetime('now')),
                    ended_at TEXT,
                    summary TEXT,
                    message_count INTEGER DEFAULT 0,
                    tool_call_count INTEGER DEFAULT 0
                );

                CREATE TABLE IF NOT EXISTS journal (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    content TEXT NOT NULL,
                    topic TEXT,
                    created_at TEXT DEFAULT (datetime('now'))
                );
            """)
            conn.commit()
            conn.close()

    # ── CRUD ──────────────────────────────────────────────────────────

    def store(
        self, content: str, importance: float = 0.5,
        tags: list[str] | None = None, source: str = "conversation",
    ) -> int:
        """Store a new memory and return its ID."""
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "INSERT INTO memories (content, importance, tags, source) VALUES (?, ?, ?, ?)",
                (content, importance, json.dumps(tags or []), source),
            )
            conn.commit()
            mem_id = cursor.lastrowid
            conn.close()
            return mem_id

    def search(self, query: str, top_k: int = 5) -> list[dict]:
        """Full-text search for memories matching the query."""
        with self._lock:
            conn = self._connect()
            conn.create_function("rank", 1, lambda x: x)
            try:
                rows = conn.execute(
                    """SELECT m.id, m.content, m.importance, m.created_at,
                              m.access_count, m.tags, m.source
                       FROM memories m
                       INNER JOIN memories_fts fts ON m.id = fts.rowid
                       WHERE memories_fts MATCH ?
                       ORDER BY rank
                       LIMIT ?""",
                    (query, top_k),
                ).fetchall()
            except sqlite3.OperationalError:
                rows = []
            conn.close()

        return [self._row_to_dict(r) for r in rows]

    def search_recent(self, n: int = 20) -> list[dict]:
        """Get the most recent memories."""
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM memories ORDER BY created_at DESC LIMIT ?",
                (n,),
            ).fetchall()
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def search_by_keywords(self, keywords: list[str], top_k: int = 5) -> list[dict]:
        """Search by simple keyword matching in content."""
        with self._lock:
            conn = self._connect()
            conditions = " OR ".join(["content LIKE ?" for _ in keywords])
            params = [f"%{kw}%" for kw in keywords]
            rows = conn.execute(
                f"SELECT * FROM memories WHERE {conditions} ORDER BY importance DESC LIMIT ?",
                (*params, top_k),
            ).fetchall()
            conn.close()
        return [self._row_to_dict(r) for r in rows]

    def get_stats(self) -> dict:
        """Return memory statistics."""
        with self._lock:
            conn = self._connect()
            total = conn.execute("SELECT COUNT(*) FROM memories").fetchone()[0]
            sessions = conn.execute("SELECT COUNT(*) FROM sessions").fetchone()[0]
            avg_imp = conn.execute(
                "SELECT AVG(importance) FROM memories"
            ).fetchone()[0] or 0.5
            conn.close()
        return {
            "total_memories": total,
            "total_sessions": sessions,
            "avg_importance": round(avg_imp, 2),
        }

    # ── Sessions ──────────────────────────────────────────────────────

    def start_session(self) -> int:
        with self._lock:
            conn = self._connect()
            cursor = conn.execute("INSERT INTO sessions DEFAULT VALUES")
            conn.commit()
            sid = cursor.lastrowid
            conn.close()
            return sid

    def end_session(self, session_id: int, summary: str = "") -> None:
        with self._lock:
            conn = self._connect()
            conn.execute(
                "UPDATE sessions SET ended_at = datetime('now'), summary = ? WHERE id = ?",
                (summary, session_id),
            )
            conn.commit()
            conn.close()

    # ── Journal ───────────────────────────────────────────────────────

    def write_journal(self, content: str, topic: str = "") -> int:
        with self._lock:
            conn = self._connect()
            cursor = conn.execute(
                "INSERT INTO journal (content, topic) VALUES (?, ?)",
                (content, topic),
            )
            conn.commit()
            jid = cursor.lastrowid
            conn.close()
            return jid

    def get_recent_journal(self, n: int = 5) -> list[dict]:
        with self._lock:
            conn = self._connect()
            rows = conn.execute(
                "SELECT * FROM journal ORDER BY created_at DESC LIMIT ?", (n,)
            ).fetchall()
            conn.close()
        return [
            {"id": r[0], "content": r[1], "topic": r[2], "created_at": r[3]}
            for r in rows
        ]

    # ── Helpers ───────────────────────────────────────────────────────

    def _row_to_dict(self, row: tuple) -> dict:
        return {
            "id": row[0],
            "content": row[1],
            "importance": row[2],
            "created_at": row[3],
            "last_accessed_at": row[4] if len(row) > 4 else None,
            "access_count": row[5] if len(row) > 5 else 0,
            "tags": row[6] if len(row) > 6 else "[]",
            "source": row[7] if len(row) > 7 else "conversation",
        }
