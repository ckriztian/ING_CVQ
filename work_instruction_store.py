"""Persistencia SQLite del gestor de Instrucciones de Trabajo."""

import base64
import binascii
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional


REVISION_STATUSES = ("draft", "active", "obsolete")
EPP_OPTIONS = (
    "Pulsera", "Talonera", "Cofia", "Guantes", "Zapatos de Seguridad",
    "Protección Auditiva", "Anteojos de Seguridad", "Máscara de seguridad",
)
ALLOWED_IMAGES = {
    "image/jpeg": ("jpg", (b"\xff\xd8\xff",)),
    "image/png": ("png", (b"\x89PNG\r\n\x1a\n",)),
    "image/webp": ("webp", (b"RIFF",)),
}
MAX_IMAGE_BYTES = 10 * 1024 * 1024


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


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
        conn.executescript("""
        CREATE TABLE IF NOT EXISTS instruction_sequence (
            singleton INTEGER PRIMARY KEY CHECK(singleton=1), next_value INTEGER NOT NULL
        );
        INSERT OR IGNORE INTO instruction_sequence VALUES (1, 1);
        CREATE TABLE IF NOT EXISTS instructions (
            instruction_id TEXT PRIMARY KEY, model_id TEXT NOT NULL,
            document_code TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
        );
        CREATE INDEX IF NOT EXISTS idx_instruction_model ON instructions(model_id);
        CREATE INDEX IF NOT EXISTS idx_instruction_code ON instructions(document_code);
        CREATE TABLE IF NOT EXISTS revisions (
            id INTEGER PRIMARY KEY AUTOINCREMENT, instruction_id TEXT NOT NULL,
            revision_code TEXT NOT NULL, status TEXT NOT NULL CHECK(status IN ('draft','active','obsolete')),
            area TEXT NOT NULL, process TEXT NOT NULL, title TEXT NOT NULL,
            prepared_by TEXT NOT NULL, reviewed_by TEXT NOT NULL, approved_by TEXT,
            document_date TEXT NOT NULL, distribution TEXT, created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
            FOREIGN KEY(instruction_id) REFERENCES instructions(instruction_id) ON DELETE CASCADE,
            UNIQUE(instruction_id, revision_code)
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_one_active_revision ON revisions(instruction_id) WHERE status='active';
        CREATE TABLE IF NOT EXISTS steps (
            id INTEGER PRIMARY KEY AUTOINCREMENT, revision_id INTEGER NOT NULL,
            position INTEGER NOT NULL, instruction TEXT NOT NULL DEFAULT '', observation TEXT, warning TEXT,
            FOREIGN KEY(revision_id) REFERENCES revisions(id) ON DELETE CASCADE,
            UNIQUE(revision_id, position)
        );
        CREATE TABLE IF NOT EXISTS images (
            id INTEGER PRIMARY KEY AUTOINCREMENT, step_id INTEGER NOT NULL UNIQUE,
            relative_path TEXT NOT NULL, mime_type TEXT NOT NULL, size_bytes INTEGER NOT NULL,
            FOREIGN KEY(step_id) REFERENCES steps(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS materials (
            id INTEGER PRIMARY KEY AUTOINCREMENT, revision_id INTEGER NOT NULL, position INTEGER NOT NULL,
            reference TEXT, description TEXT NOT NULL, code TEXT, quantity TEXT NOT NULL, notes TEXT,
            FOREIGN KEY(revision_id) REFERENCES revisions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS tools (
            id INTEGER PRIMARY KEY AUTOINCREMENT, revision_id INTEGER NOT NULL, position INTEGER NOT NULL,
            description TEXT NOT NULL, specification TEXT, quantity TEXT NOT NULL,
            FOREIGN KEY(revision_id) REFERENCES revisions(id) ON DELETE CASCADE
        );
        CREATE TABLE IF NOT EXISTS revision_epp (
            revision_id INTEGER NOT NULL, epp_name TEXT NOT NULL, selected INTEGER NOT NULL CHECK(selected IN (0,1)),
            PRIMARY KEY(revision_id, epp_name),
            FOREIGN KEY(revision_id) REFERENCES revisions(id) ON DELETE CASCADE
        );
        """)


def _revision(conn: sqlite3.Connection, revision_id: int) -> Dict[str, Any]:
    rev = conn.execute("SELECT * FROM revisions WHERE id=?", (revision_id,)).fetchone()
    result = dict(rev)
    steps = []
    for row in conn.execute("SELECT * FROM steps WHERE revision_id=? ORDER BY position", (revision_id,)):
        step = dict(row)
        image = conn.execute("SELECT relative_path,mime_type,size_bytes FROM images WHERE step_id=?", (row["id"],)).fetchone()
        step["image"] = dict(image) if image else None
        steps.append(step)
    result["steps"] = steps
    result["materials"] = [dict(x) for x in conn.execute("SELECT * FROM materials WHERE revision_id=? ORDER BY position", (revision_id,))]
    result["tools"] = [dict(x) for x in conn.execute("SELECT * FROM tools WHERE revision_id=? ORDER BY position", (revision_id,))]
    selected = {x["epp_name"]: bool(x["selected"]) for x in conn.execute("SELECT * FROM revision_epp WHERE revision_id=?", (revision_id,))}
    result["epp"] = [{"name": name, "selected": selected.get(name, False)} for name in EPP_OPTIONS]
    return result


def get_instruction(path: Path, instruction_id: str) -> Optional[Dict[str, Any]]:
    initialize(path)
    with connection(path) as conn:
        item = conn.execute("SELECT * FROM instructions WHERE instruction_id=?", (instruction_id,)).fetchone()
        if not item:
            return None
        result = dict(item)
        revisions = conn.execute("SELECT id FROM revisions WHERE instruction_id=? ORDER BY id DESC", (instruction_id,)).fetchall()
        result["revisions"] = [_revision(conn, row["id"]) for row in revisions]
        result["current_revision"] = next((x for x in result["revisions"] if x["status"] == "active"), result["revisions"][0])
        return result


def list_instructions(path: Path, model_id: Optional[str] = None) -> List[Dict[str, Any]]:
    initialize(path)
    where, args = ("WHERE i.model_id=?", (model_id,)) if model_id else ("", ())
    with connection(path) as conn:
        rows = conn.execute(f"""SELECT i.*, r.revision_code AS current_revision,
            COALESCE(r.status, 'draft') AS status, COALESCE(r.process, '') AS process,
            COALESCE(r.title, '') AS title
            FROM instructions i LEFT JOIN revisions r ON r.id=(
              SELECT id FROM revisions WHERE instruction_id=i.instruction_id
              ORDER BY CASE status WHEN 'active' THEN 0 WHEN 'draft' THEN 1 ELSE 2 END, id DESC LIMIT 1)
            {where} ORDER BY i.updated_at DESC""", args).fetchall()
    return [dict(row) for row in rows]


def _replace_children(conn: sqlite3.Connection, revision_id: int, values: Dict[str, Any]) -> None:
    if "steps" in values:
        previous_images = {
            row["position"]: dict(row)
            for row in conn.execute("""SELECT s.position,i.relative_path,i.mime_type,i.size_bytes
                FROM steps s JOIN images i ON i.step_id=s.id WHERE s.revision_id=?""", (revision_id,))
        }
        conn.execute("DELETE FROM steps WHERE revision_id=?", (revision_id,))
        for position, step in enumerate(values["steps"], 1):
            cursor = conn.execute("INSERT INTO steps(revision_id,position,instruction,observation,warning) VALUES(?,?,?,?,?)",
                                  (revision_id, position, step.get("instruction", ""), step.get("observation"), step.get("warning")))
            image = step.get("image") or previous_images.get(position)
            if image:
                conn.execute("INSERT INTO images(step_id,relative_path,mime_type,size_bytes) VALUES(?,?,?,?)",
                             (cursor.lastrowid, image["relative_path"], image["mime_type"], image["size_bytes"]))
    if "materials" in values:
        conn.execute("DELETE FROM materials WHERE revision_id=?", (revision_id,))
        for position, item in enumerate(values["materials"], 1):
            conn.execute("INSERT INTO materials(revision_id,position,reference,description,code,quantity,notes) VALUES(?,?,?,?,?,?,?)",
                         (revision_id, position, item.get("reference"), item["description"], item.get("code"), str(item["quantity"]), item.get("notes")))
    if "tools" in values:
        conn.execute("DELETE FROM tools WHERE revision_id=?", (revision_id,))
        for position, item in enumerate(values["tools"], 1):
            conn.execute("INSERT INTO tools(revision_id,position,description,specification,quantity) VALUES(?,?,?,?,?)",
                         (revision_id, position, item["description"], item.get("specification"), str(item["quantity"])))
    if "epp" in values:
        conn.execute("DELETE FROM revision_epp WHERE revision_id=?", (revision_id,))
        epp = {x["name"]: bool(x.get("selected")) for x in values["epp"]}
        conn.executemany("INSERT INTO revision_epp VALUES(?,?,?)", [(revision_id, name, int(epp.get(name, False))) for name in EPP_OPTIONS])


def create_instruction(path: Path, model_id: str, values: Dict[str, Any]) -> Dict[str, Any]:
    initialize(path)
    stamp = now()
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        sequence = conn.execute("SELECT next_value FROM instruction_sequence WHERE singleton=1").fetchone()[0]
        conn.execute("UPDATE instruction_sequence SET next_value=? WHERE singleton=1", (sequence + 1,))
        instruction_id = f"IT-{sequence:06d}"
        conn.execute("INSERT INTO instructions VALUES(?,?,?,?,?)", (instruction_id, model_id, values["document_code"], stamp, stamp))
        cursor = conn.execute("""INSERT INTO revisions(instruction_id,revision_code,status,area,process,title,prepared_by,
            reviewed_by,approved_by,document_date,distribution,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (instruction_id, values["revision_code"], values.get("status", "draft"), values["area"], values["process"],
             values["title"], values["prepared_by"], values["reviewed_by"], values.get("approved_by"),
             values["document_date"], values.get("distribution"), stamp, stamp))
        children = {**values}
        children.setdefault("steps", [])
        children.setdefault("materials", [])
        children.setdefault("tools", [])
        children.setdefault("epp", [])
        _replace_children(conn, cursor.lastrowid, children)
    return get_instruction(path, instruction_id)


def update_instruction(path: Path, instruction_id: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    initialize(path)
    with connection(path) as conn:
        if "document_code" in values:
            conn.execute("UPDATE instructions SET document_code=?,updated_at=? WHERE instruction_id=?", (values["document_code"], now(), instruction_id))
        exists = conn.execute("SELECT 1 FROM instructions WHERE instruction_id=?", (instruction_id,)).fetchone()
    return get_instruction(path, instruction_id) if exists else None


def update_revision(path: Path, instruction_id: str, revision_code: str, values: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    initialize(path)
    fields = ("area", "process", "title", "prepared_by", "reviewed_by", "approved_by", "document_date", "distribution")
    with connection(path) as conn:
        row = conn.execute("SELECT id,status FROM revisions WHERE instruction_id=? AND revision_code=?", (instruction_id, revision_code)).fetchone()
        if not row:
            return None
        if row["status"] != "draft":
            raise ValueError("Solo una revisión draft puede editarse")
        updates = [(key, values[key]) for key in fields if key in values]
        if updates:
            conn.execute(f"UPDATE revisions SET {','.join(k+'=?' for k,_ in updates)},updated_at=? WHERE id=?", [v for _,v in updates] + [now(), row["id"]])
        _replace_children(conn, row["id"], values)
        conn.execute("UPDATE instructions SET updated_at=? WHERE instruction_id=?", (now(), instruction_id))
    return get_instruction(path, instruction_id)


def new_revision(path: Path, instruction_id: str, revision_code: str) -> Optional[Dict[str, Any]]:
    source = get_instruction(path, instruction_id)
    if not source:
        return None
    base = source["current_revision"]
    initialize(path)
    stamp = now()
    with connection(path) as conn:
        cursor = conn.execute("""INSERT INTO revisions(instruction_id,revision_code,status,area,process,title,prepared_by,
            reviewed_by,approved_by,document_date,distribution,created_at,updated_at) VALUES(?,?, 'draft',?,?,?,?,?,?,?,?,?,?)""",
            (instruction_id, revision_code, base["area"], base["process"], base["title"], base["prepared_by"],
             base["reviewed_by"], base["approved_by"], base["document_date"], base["distribution"], stamp, stamp))
        _replace_children(conn, cursor.lastrowid, base)
        conn.execute("UPDATE instructions SET updated_at=? WHERE instruction_id=?", (stamp, instruction_id))
    return get_instruction(path, instruction_id)


def activate_revision(path: Path, instruction_id: str, revision_code: str) -> Optional[Dict[str, Any]]:
    initialize(path)
    with connection(path) as conn:
        conn.execute("BEGIN IMMEDIATE")
        target = conn.execute("SELECT id,status FROM revisions WHERE instruction_id=? AND revision_code=?", (instruction_id, revision_code)).fetchone()
        if not target:
            return None
        if target["status"] != "draft":
            raise ValueError("Solo una revisión draft puede activarse")
        conn.execute("UPDATE revisions SET status='obsolete',updated_at=? WHERE instruction_id=? AND status='active'", (now(), instruction_id))
        conn.execute("UPDATE revisions SET status='active',updated_at=? WHERE id=?", (now(), target["id"]))
        conn.execute("UPDATE instructions SET updated_at=? WHERE instruction_id=?", (now(), instruction_id))
    return get_instruction(path, instruction_id)


def save_step_image(db_path: Path, data_root: Path, instruction_id: str, revision_code: str,
                    position: int, mime_type: str, encoded: str) -> Dict[str, Any]:
    if mime_type not in ALLOWED_IMAGES or position < 1:
        raise ValueError("Formato o procedimiento inválido")
    try:
        raw = base64.b64decode(encoded, validate=True)
    except (binascii.Error, ValueError) as exc:
        raise ValueError("Imagen base64 inválida") from exc
    extension, signatures = ALLOWED_IMAGES[mime_type]
    valid = any(raw.startswith(signature) for signature in signatures)
    if mime_type == "image/webp":
        valid = valid and len(raw) >= 12 and raw[8:12] == b"WEBP"
    if not valid or not raw or len(raw) > MAX_IMAGE_BYTES:
        raise ValueError("Contenido o tamaño de imagen inválido")
    if any("/" in value or "\\" in value or ".." in value for value in (instruction_id, revision_code)):
        raise ValueError("Ruta de imagen inválida")
    instruction = get_instruction(db_path, instruction_id)
    if not instruction:
        raise LookupError("IT no encontrada")
    revision = next((x for x in instruction["revisions"] if x["revision_code"] == revision_code), None)
    if not revision or revision["status"] != "draft":
        raise ValueError("La imagen requiere una revisión draft")
    step = next((x for x in revision["steps"] if x["position"] == position), None)
    if not step:
        raise LookupError("Procedimiento no encontrado")
    relative = Path(instruction_id) / revision_code / f"step_{position:02d}_01.{extension}"
    destination = (data_root / relative).resolve()
    if data_root.resolve() not in destination.parents:
        raise ValueError("Ruta de imagen inválida")
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(raw)
    with connection(db_path) as conn:
        previous = conn.execute("SELECT relative_path FROM images WHERE step_id=?", (step["id"],)).fetchone()
        conn.execute("INSERT OR REPLACE INTO images(step_id,relative_path,mime_type,size_bytes) VALUES(?,?,?,?)",
                     (step["id"], relative.as_posix(), mime_type, len(raw)))
    if previous and previous["relative_path"] != relative.as_posix():
        (data_root / previous["relative_path"]).unlink(missing_ok=True)
    return {"relative_path": relative.as_posix(), "mime_type": mime_type, "size_bytes": len(raw)}
