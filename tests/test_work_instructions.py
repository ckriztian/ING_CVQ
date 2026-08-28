import base64
import sqlite3

import pytest

import main
from work_instruction_store import EPP_OPTIONS, activate_revision, create_instruction
from work_instruction_store import get_instruction, initialize, new_revision, save_step_image, update_revision


def payload(**overrides):
    values = {
        "document_code": "BSIP IT TEST",
        "revision_code": "R0",
        "status": "active",
        "area": "A. A.",
        "process": "Montaje",
        "title": "Fijación de componente",
        "prepared_by": "Ingeniería",
        "reviewed_by": "Calidad",
        "approved_by": None,
        "document_date": "2026-08-27",
        "distribution": "L3",
        "steps": [
            {"instruction": "Tomar componente.", "observation": "Mantener limpio", "warning": None},
            {"instruction": "Fijar componente.", "observation": None, "warning": "Verificar torque"},
        ],
        "materials": [{"reference": "a", "description": "Tornillo", "code": "123", "quantity": "2", "notes": None}],
        "tools": [{"description": "Atornilladora", "specification": "PH2", "quantity": "1"}],
        "epp": [{"name": name, "selected": name in {"Pulsera", "Guantes"}} for name in EPP_OPTIONS],
    }
    values.update(overrides)
    return values


def test_store_identity_relations_and_revision_transaction(tmp_path):
    db = tmp_path / "work_instructions.db"
    first = create_instruction(db, "mdl_000002", payload())
    second = create_instruction(db, "mdl_000002", payload(document_code="MISMO CÓDIGO CORPORATIVO"))
    assert first["instruction_id"] == "IT-000001"
    assert second["instruction_id"] == "IT-000002"
    assert first["model_id"] == "mdl_000002"
    assert len(first["current_revision"]["steps"]) == 2
    assert first["current_revision"]["materials"][0]["code"] == "123"
    assert first["current_revision"]["tools"][0]["specification"] == "PH2"
    assert {x["name"] for x in first["current_revision"]["epp"] if x["selected"]} == {"Pulsera", "Guantes"}

    copied = new_revision(db, "IT-000001", "R1")
    assert copied["current_revision"]["revision_code"] == "R0"
    draft = next(x for x in copied["revisions"] if x["revision_code"] == "R1")
    assert draft["status"] == "draft" and len(draft["steps"]) == 2
    update_revision(db, "IT-000001", "R1", {"steps": [draft["steps"][1], draft["steps"][0], draft["steps"][0]]})
    published = activate_revision(db, "IT-000001", "R1")
    statuses = {x["revision_code"]: x["status"] for x in published["revisions"]}
    assert statuses == {"R1": "active", "R0": "obsolete"}
    assert [x["position"] for x in published["current_revision"]["steps"]] == [1, 2, 3]
    with sqlite3.connect(db) as conn:
        assert conn.execute("SELECT COUNT(*) FROM revisions WHERE status='active' AND instruction_id='IT-000001'").fetchone()[0] == 1


def test_images_are_files_validated_and_paths_cannot_escape(tmp_path):
    db, root = tmp_path / "work_instructions.db", tmp_path / "images"
    create_instruction(db, "mdl_000002", payload(status="draft"))
    png = b"\x89PNG\r\n\x1a\n" + b"valid-test-image"
    image = save_step_image(db, root, "IT-000001", "R0", 1, "image/png", base64.b64encode(png).decode())
    assert image["relative_path"] == "IT-000001/R0/step_01_01.png"
    assert (root / image["relative_path"]).read_bytes() == png
    assert get_instruction(db, "IT-000001")["current_revision"]["steps"][0]["image"]["mime_type"] == "image/png"
    with pytest.raises(ValueError, match="Ruta"):
        save_step_image(db, root, "../escape", "R0", 1, "image/png", base64.b64encode(png).decode())
    with pytest.raises(ValueError, match="Contenido"):
        save_step_image(db, root, "IT-000001", "R0", 1, "image/jpeg", base64.b64encode(png).decode())


def test_schema_has_all_separate_work_instruction_tables(tmp_path):
    db = tmp_path / "work_instructions.db"
    initialize(db)
    with sqlite3.connect(db) as conn:
        tables = {x[0] for x in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert {"instructions", "revisions", "steps", "materials", "tools", "revision_epp", "images"} <= tables


def test_frontend_has_manager_preview_and_writing_assistance():
    html = (main.BASE_DIR / "index.html").read_text(encoding="utf-8")
    assert "Instrucciones de Trabajo" in html
    assert "MODO CONSULTA" in html and "Editar IT" in html
    assert "Duplicar procedimiento" in html and "moveWorkStep" in html
    assert "WI_ACTIONS" in html and all(action in html for action in ("Tomar", "Atornillar", "Rutear", "Retirar"))
    assert "Plantillas de frase" in html and "Verificar correcta posición" in html
    assert "Vista previa" in html and "renderWorkPreview" in html
