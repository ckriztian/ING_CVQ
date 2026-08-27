"""Persistencia SQLite dedicada a la memoria de Ingeniería."""

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


CHANGE_TYPES = {
    "material_component": "Material / componente",
    "process": "Proceso",
    "work_method": "Método de trabajo",
    "tooling": "Herramental",
    "quality": "Calidad",
    "layout": "Layout",
    "parameter": "Parámetro",
    "documentation": "Documentación",
    "engineering_observation": "Observación de Ingeniería",
    "other": "Otro",
}

CHANGE_STATUSES = {
    "evaluation": "En evaluación",
    "active": "Vigente",
    "superseded": "Reemplazado",
    "closed": "Cerrado",
}


@contextmanager
def connection(path: Path) -> Iterator[sqlite3.Connection]:
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(path, timeout=5.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA journal_mode = WAL")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def initialize(path: Path) -> None:
    with connection(path) as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS engineering_change_sequence (
                singleton INTEGER PRIMARY KEY CHECK (singleton = 1),
                next_value INTEGER NOT NULL CHECK (next_value > 0)
            );
            INSERT OR IGNORE INTO engineering_change_sequence(singleton, next_value) VALUES (1, 1);

            CREATE TABLE IF NOT EXISTS engineering_changes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                change_id TEXT NOT NULL UNIQUE,
                model_id TEXT NOT NULL,
                change_type TEXT NOT NULL,
                title TEXT NOT NULL,
                sector TEXT,
                description TEXT NOT NULL,
                old_code TEXT,
                new_code TEXT,
                reason TEXT,
                status TEXT NOT NULL,
                remind_next_production INTEGER NOT NULL DEFAULT 0 CHECK (remind_next_production IN (0, 1)),
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                created_by TEXT,
                notes TEXT
            );
            CREATE INDEX IF NOT EXISTS idx_changes_model_id ON engineering_changes(model_id);
            CREATE INDEX IF NOT EXISTS idx_changes_status ON engineering_changes(status);
            CREATE INDEX IF NOT EXISTS idx_changes_created_at ON engineering_changes(created_at DESC);
            CREATE INDEX IF NOT EXISTS idx_changes_model_reminder
                ON engineering_changes(model_id, status, remind_next_production);
            CREATE INDEX IF NOT EXISTS idx_changes_type ON engineering_changes(change_type);
            """
        )


def _serialize(row: sqlite3.Row) -> Dict[str, Any]:
    item = dict(row)
    item["remind_next_production"] = bool(item["remind_next_production"])
    return item


def create_change(path: Path, model_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    initialize(path)
    now = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sequence = conn.execute(
            "SELECT next_value FROM engineering_change_sequence WHERE singleton = ?", (1,)
        ).fetchone()["next_value"]
        conn.execute(
            "UPDATE engineering_change_sequence SET next_value = ? WHERE singleton = ?", (sequence + 1, 1)
        )
        change_id = f"CHG-{sequence:06d}"
        cursor = conn.execute(
            """INSERT INTO engineering_changes (
                change_id, model_id, change_type, title, sector, description,
                old_code, new_code, reason, status, remind_next_production,
                created_at, updated_at, created_by, notes
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                change_id, model_id, values["change_type"], values["title"], values.get("sector"),
                values["description"], values.get("old_code"), values.get("new_code"), values.get("reason"),
                values["status"], int(values["remind_next_production"]), now, now,
                values.get("created_by"), values.get("notes"),
            ),
        )
        row = conn.execute("SELECT * FROM engineering_changes WHERE id = ?", (cursor.lastrowid,)).fetchone()
    return _serialize(row)


def list_changes(
    path: Path,
    model_id: str,
    *,
    status: Optional[str] = None,
    change_type: Optional[str] = None,
    remind_next_production: Optional[bool] = None,
) -> List[Dict[str, Any]]:
    initialize(path)
    clauses, parameters = ["model_id = ?"], [model_id]
    if status is not None:
        clauses.append("status = ?")
        parameters.append(status)
    if change_type is not None:
        clauses.append("change_type = ?")
        parameters.append(change_type)
    if remind_next_production is not None:
        clauses.append("remind_next_production = ?")
        parameters.append(int(remind_next_production))
    query = "SELECT * FROM engineering_changes WHERE " + " AND ".join(clauses) + " ORDER BY created_at DESC, id DESC"
    with connection(path) as conn:
        rows = conn.execute(query, parameters).fetchall()
    return [_serialize(row) for row in rows]


def get_change(path: Path, change_id: str) -> Optional[Dict[str, Any]]:
    initialize(path)
    with connection(path) as conn:
        row = conn.execute("SELECT * FROM engineering_changes WHERE change_id = ?", (change_id,)).fetchone()
    return _serialize(row) if row else None


def update_change(path: Path, change_id: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    initialize(path)
    allowed = (
        "change_type", "title", "sector", "description", "old_code", "new_code",
        "reason", "status", "remind_next_production", "created_by", "notes",
    )
    updates = [(field, values[field]) for field in allowed if field in values]
    if not updates:
        return get_change(path, change_id)
    assignments = ", ".join(f"{field} = ?" for field, _ in updates)
    parameters = [int(value) if field == "remind_next_production" else value for field, value in updates]
    parameters.extend([datetime.now(timezone.utc).isoformat(timespec="seconds"), change_id])
    with connection(path) as conn:
        cursor = conn.execute(
            f"UPDATE engineering_changes SET {assignments}, updated_at = ? WHERE change_id = ?", parameters
        )
        if not cursor.rowcount:
            return None
        row = conn.execute("SELECT * FROM engineering_changes WHERE change_id = ?", (change_id,)).fetchone()
    return _serialize(row)
