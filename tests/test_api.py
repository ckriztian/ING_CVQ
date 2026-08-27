import asyncio
import json
import sqlite3
import shutil
from urllib.parse import urlsplit

import pytest

import main


ADMIN_KEY = "test-suite-only"
MODEL_QUERY = "capacidad=12k&proveedor=midea&modelo=inv"


class Response:
    def __init__(self, status_code, headers, body):
        self.status_code = status_code
        self.headers = headers
        self.content = body
        self.text = body.decode("utf-8")

    def json(self):
        return json.loads(self.text)


class AsgiClient:
    """Cliente ASGI mínimo para no depender de paquetes ajenos al runtime."""

    def __init__(self, app):
        self.app = app

    def request(self, method, url, json=None, headers=None):
        return asyncio.run(self._request(method, url, json, headers or {}))

    async def _request(self, method, url, payload, headers):
        parsed = urlsplit(url)
        body = b"" if payload is None else json_module.dumps(payload).encode("utf-8")
        request_headers = [(key.lower().encode(), value.encode()) for key, value in headers.items()]
        if payload is not None:
            request_headers.append((b"content-type", b"application/json"))
        scope = {
            "type": "http", "asgi": {"version": "3.0"}, "http_version": "1.1",
            "method": method, "scheme": "http", "path": parsed.path,
            "raw_path": parsed.path.encode(), "query_string": parsed.query.encode(),
            "headers": request_headers, "client": ("test", 1), "server": ("test", 80),
        }
        sent = False
        messages = []

        async def receive():
            nonlocal sent
            if not sent:
                sent = True
                return {"type": "http.request", "body": body, "more_body": False}
            return {"type": "http.disconnect"}

        async def send(message):
            messages.append(message)

        try:
            await self.app(scope, receive, send)
        except Exception:
            if not messages:
                raise
        start = next(message for message in messages if message["type"] == "http.response.start")
        response_body = b"".join(message.get("body", b"") for message in messages if message["type"] == "http.response.body")
        response_headers = {key.decode(): value.decode() for key, value in start.get("headers", [])}
        return Response(start["status"], response_headers, response_body)

    def get(self, url, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url, **kwargs):
        return self.request("POST", url, **kwargs)

    def put(self, url, **kwargs):
        return self.request("PUT", url, **kwargs)

    def patch(self, url, **kwargs):
        return self.request("PATCH", url, **kwargs)

    def delete(self, url, **kwargs):
        return self.request("DELETE", url, **kwargs)


json_module = json


@pytest.fixture()
def client(tmp_path, monkeypatch):
    paths = {}
    for attribute, filename in [
        ("CSV_PATH", "palletizacion.csv"),
        ("ESPEC_PATH", "especificaciones.csv"),
        ("PERSONAL_PATH", "personal_linea.json"),
        ("LAYOUTS_PATH", "layouts.json"),
        ("TIEMPOS_PATH", "tiempos_linea.json"),
        ("MODELOS_PATH", "modelos.json"),
    ]:
        target = tmp_path / filename
        shutil.copy2(main.BASE_DIR / filename, target)
        monkeypatch.setattr(main, attribute, target)
        paths[attribute] = target
    monkeypatch.setattr(main, "KB", main.load_knowledge(paths["CSV_PATH"]))
    monkeypatch.setattr(main, "SPECS", main.load_specs(paths["ESPEC_PATH"]))
    monkeypatch.setattr(main, "PERSONAL", main.load_json(paths["PERSONAL_PATH"], "personal test"))
    monkeypatch.setattr(main, "LAYOUTS", main.load_json(paths["LAYOUTS_PATH"], "layouts test"))
    monkeypatch.setattr(main, "TIEMPOS", main.load_json(paths["TIEMPOS_PATH"], "tiempos test"))
    models = main.load_models(paths["MODELOS_PATH"])
    monkeypatch.setattr(main, "MODELOS", models)
    monkeypatch.setattr(main, "MODELS_BY_ID", {item["model_id"]: item for item in models})
    monkeypatch.setattr(main, "MODEL_ID_BY_KEY", {
        (main.norm(item["capacidad"]), main.norm(item["proveedor"]), main.norm(item["modelo"])): item["model_id"]
        for item in models
    })
    monkeypatch.setattr(main, "HISTORY_DB_PATH", tmp_path / "engineering_history.db")
    monkeypatch.setattr(main, "WORK_INSTRUCTIONS_DB_PATH", tmp_path / "work_instructions.db")
    monkeypatch.setattr(main, "WORK_INSTRUCTION_FILES_PATH", tmp_path / "work_instruction_files")
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    yield AsgiClient(main.app)


def auth():
    return {"X-API-Key": ADMIN_KEY}


def work_instruction_payload(**overrides):
    values = {
        "document_code": "BSIP IT TEST", "revision_code": "R0", "status": "draft",
        "area": "A. A.", "process": "Montaje", "title": "Fijación",
        "prepared_by": "Ingeniería", "reviewed_by": "Calidad", "approved_by": None,
        "document_date": "2026-08-27", "distribution": "L3",
        "steps": [{"instruction": "Tomar componente.", "observation": None, "warning": None}],
        "materials": [], "tools": [], "epp": [],
    }
    values.update(overrides)
    return values


def test_work_instruction_api_security_revisions_and_export_503(client):
    body = work_instruction_payload()
    assert client.post("/modelos/mdl_000002/instrucciones", json=body).status_code == 401
    created = client.post("/modelos/mdl_000002/instrucciones", json=body, headers=auth())
    assert created.status_code == 201
    assert created.json()["instruction_id"] == "IT-000001"
    assert client.get("/instrucciones").json()[0]["model_id"] == "mdl_000002"
    assert client.get("/modelos/mdl_000002/instrucciones").json()[0]["document_code"] == "BSIP IT TEST"
    assert client.patch("/instrucciones/IT-000001/revisiones/R0", json={"title": "Sin permiso"}).status_code == 401
    patched = client.patch("/instrucciones/IT-000001/revisiones/R0", json={"title": "Título actualizado"}, headers=auth())
    assert patched.status_code == 200 and patched.json()["current_revision"]["title"] == "Título actualizado"
    assert client.post("/instrucciones/IT-000001/revisiones", json={"revision_code": "R1"}, headers=auth()).status_code == 201
    activated = client.post("/instrucciones/IT-000001/revisiones/R1/activar", headers=auth())
    assert activated.status_code == 200
    assert sum(x["status"] == "active" for x in activated.json()["revisions"]) == 1
    export = client.get("/instrucciones/IT-000001/exportar")
    assert export.status_code == 503 and "todavía no está disponible" in export.json()["detail"]


def test_work_instruction_api_rejects_unknown_model_and_epp(client):
    assert client.post("/modelos/mdl_missing/instrucciones", json=work_instruction_payload(), headers=auth()).status_code == 404
    bad = work_instruction_payload(epp=[{"name": "Casco inventado", "selected": True}])
    assert client.post("/modelos/mdl_000002/instrucciones", json=bad, headers=auth()).status_code == 422


def test_health(client):
    response = client.get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_catalog_and_lines(client):
    assert len(client.get("/catalogo").json()) == 20
    assert client.get("/lineas").json() == ["L01", "L03"]


def test_pallet_valid_and_missing(client):
    valid = client.get(f"/pallets?{MODEL_QUERY}")
    assert valid.status_code == 200
    assert valid.json()["unidades_por_pallet"] == 12
    assert client.get("/pallets?capacidad=99k&proveedor=x&modelo=x").status_code == 404


def test_calculate_pallets_valid_and_invalid(client):
    payload = {"capacidad": "12k", "proveedor": "midea", "modelo": "inv", "cantidad": 25}
    result = client.post("/calcular-pallets", json=payload)
    assert result.status_code == 200
    assert result.json()["pallets_totales"] == 3
    payload["cantidad"] = 0
    assert client.post("/calcular-pallets", json=payload).status_code == 422


def test_specs_existing_and_missing(client):
    assert client.get(f"/specs?{MODEL_QUERY}&linea=L01").status_code == 200
    assert client.get(f"/specs?{MODEL_QUERY}&linea=NO_EXISTE").status_code == 404


def test_personal_read_and_authorization(client):
    assert client.get(f"/personal?{MODEL_QUERY}").status_code == 200
    payload = {"nombre_modelo": "Prueba", "tramos": [{"nombre": "Puesto", "personas": 1}]}
    assert client.post(f"/personal?{MODEL_QUERY}", json=payload).status_code == 401
    assert client.post(f"/personal?{MODEL_QUERY}", json=payload, headers=auth()).status_code == 200
    assert client.get(f"/personal?{MODEL_QUERY}").json()["nombre_modelo"] == "Prueba"


def test_personal_validation_and_catalog_integrity(client):
    invalid = {"tramos": [{"nombre": "Puesto", "personas": -1}]}
    assert client.post(f"/personal?{MODEL_QUERY}", json=invalid, headers=auth()).status_code == 422
    assert client.post("/personal?capacidad=99k&proveedor=x&modelo=x", json={"tramos": []}, headers=auth()).status_code == 404


def test_layout_get_put_unauthorized_and_delete(client):
    assert client.get(f"/layouts?{MODEL_QUERY}").status_code == 200
    payload = {"nombre": "Layout test", "url": "https://example.com/layout", "estado": "En prueba"}
    assert client.put(f"/layouts?{MODEL_QUERY}", json=payload).status_code == 401
    assert client.put(f"/layouts?{MODEL_QUERY}", json=payload, headers=auth()).status_code == 200
    assert client.get(f"/layouts?{MODEL_QUERY}").json()["nombre"] == "Layout test"
    assert client.delete(f"/layouts?{MODEL_QUERY}", headers=auth()).status_code == 204
    assert client.get(f"/layouts?{MODEL_QUERY}").status_code == 404


def test_times_get_put_and_delete(client):
    assert client.get(f"/tiempos?{MODEL_QUERY}").status_code == 200
    payload = {"titulo": "Test", "limite": 18, "tiempos": [10, 19]}
    assert client.put(f"/tiempos?{MODEL_QUERY}", json=payload).status_code == 401
    assert client.put(f"/tiempos?{MODEL_QUERY}", json=payload, headers=auth()).status_code == 200
    assert client.get(f"/tiempos?{MODEL_QUERY}").json()["tiempos"] == [10.0, 19.0]
    assert client.delete(f"/tiempos?{MODEL_QUERY}", headers=auth()).status_code == 204


def test_admin_authentication(client):
    assert client.get("/admin/verify", headers={"X-API-Key": "wrong"}).status_code == 401
    assert client.get("/admin/verify", headers=auth()).status_code == 200
    assert client.get("/admin/csv", headers=auth()).status_code == 200
    assert client.get("/admin/specs", headers=auth()).status_code == 200


def test_admin_is_blocked_without_configuration(client, monkeypatch):
    monkeypatch.delenv("ADMIN_API_KEY")
    assert client.get("/admin/verify", headers=auth()).status_code == 503


def test_csv_replacement_uses_temporary_files(client):
    original = client.get("/admin/csv", headers=auth()).text
    response = client.post("/admin/csv/replace", json={"csv_text": original}, headers=auth())
    assert response.status_code == 200
    assert main.CSV_PATH.with_suffix(".csv.bak").exists()


def test_sku_change_syncs_master_catalog_and_preserves_model_id(client):
    original = client.get("/admin/csv", headers=auth()).text
    old_sku = "UC.SPL.F/C BSIC37WCNX"
    new_sku = "SKU_TEST_SINCRONIZADO"
    changed = original.replace(old_sku, new_sku, 1)

    before = client.get("/modelos/mdl_000002").json()
    response = client.post("/admin/csv/replace", json={"csv_text": changed}, headers=auth())

    assert response.status_code == 200
    assert response.json()["catalog_status"] == "synchronized"
    assert response.json()["rows"] == 20
    assert new_sku in main.CSV_PATH.read_text(encoding="utf-8")
    persisted = next(item for item in main.load_models(main.MODELOS_PATH) if item["model_id"] == "mdl_000002")
    identity = client.get("/modelos/mdl_000002").json()
    summary = client.get("/modelos/mdl_000002/resumen").json()
    assert before["model_id"] == persisted["model_id"] == identity["model_id"] == summary["model_id"]
    assert persisted["sku_bgh"] == identity["sku_bgh"] == summary["identity"]["sku_bgh"] == new_sku
    assert persisted["pnb"] == before["pnb"]


def test_catalog_write_failure_leaves_csv_unchanged(client, monkeypatch):
    original = client.get("/admin/csv", headers=auth()).text
    changed = original.replace("UC.SPL.F/C BSIC37WCNX", "SKU_QUE_NO_DEBE_GUARDARSE", 1)
    monkeypatch.setattr(main, "save_models", lambda *_: (_ for _ in ()).throw(OSError("fallo simulado")))

    response = client.post("/admin/csv/replace", json={"csv_text": changed}, headers=auth())

    assert response.status_code == 500
    assert main.CSV_PATH.read_text(encoding="utf-8") == original
    assert main.load_models(main.MODELOS_PATH)[1]["sku_bgh"] == "UC.SPL.F/C BSIC37WCNX"


def test_csv_write_failure_rolls_master_catalog_back(client, monkeypatch):
    original_csv = client.get("/admin/csv", headers=auth()).text
    original_models = main.load_models(main.MODELOS_PATH)
    changed = original_csv.replace("UC.SPL.F/C BSIC37WCNX", "SKU_TRANSACCION_FALLIDA", 1)
    monkeypatch.setattr(main, "save_csv", lambda *_: (_ for _ in ()).throw(OSError("fallo CSV simulado")))

    response = client.post("/admin/csv/replace", json={"csv_text": changed}, headers=auth())

    assert response.status_code == 500
    assert main.CSV_PATH.read_text(encoding="utf-8") == original_csv
    assert main.load_models(main.MODELOS_PATH) == original_models


def test_identity_change_and_new_product_are_rejected(client):
    original = client.get("/admin/csv", headers=auth()).text
    changed_key = original.replace("12k,midea,inv,", "12k,midea,inverter,", 1)
    response = client.post("/admin/csv/replace", json={"csv_text": changed_key}, headers=auth())
    assert response.status_code == 409
    assert "cambia la identidad" in response.json()["detail"]

    first_data_row = original.splitlines()[1]
    new_product = original.rstrip("\n") + "\n" + first_data_row.replace("12k,midea,inv,", "12k,nuevo,inv,") + "\n"
    response = client.post("/admin/csv/replace", json={"csv_text": new_product}, headers=auth())
    assert response.status_code == 409
    assert main.CSV_PATH.read_text(encoding="utf-8") == original


def test_invalid_csv_does_not_replace_active_file(client):
    before = main.CSV_PATH.read_text(encoding="utf-8")
    response = client.post("/admin/csv/replace", json={"csv_text": "bad,header\n1,2"}, headers=auth())
    assert response.status_code == 422
    assert main.CSV_PATH.read_text(encoding="utf-8") == before


def test_reload_endpoints_are_protected(client):
    for endpoint in ["/reload", "/reload-specs", "/reload-layouts", "/reload-tiempos"]:
        assert client.post(endpoint).status_code == 401
        assert client.post(endpoint, headers=auth()).status_code == 200


def test_corrupt_json_is_not_treated_as_empty(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{not-json", encoding="utf-8")
    with pytest.raises(RuntimeError, match="JSON inválido"):
        main.load_json(path, "archivo de prueba")


def test_master_catalog_has_unique_ids_and_product_keys(client):
    models = client.get("/modelos").json()
    ids = [item["model_id"] for item in models]
    keys = [(item["capacidad"], item["proveedor"], item["modelo"]) for item in models]
    assert len(models) == 20
    assert len(ids) == len(set(ids))
    assert len(keys) == len(set(keys))


def test_get_existing_and_missing_master_model(client):
    response = client.get("/modelos/mdl_000002")
    assert response.status_code == 200
    assert response.json()["sku_bgh"] == "UC.SPL.F/C BSIC37WCNX"
    assert client.get("/modelos/mdl_999999").status_code == 404


def test_model_resolution_is_bidirectional():
    identity = main.resolve_model("mdl_000002")
    assert (identity["capacidad"], identity["proveedor"], identity["modelo"]) == ("12k", "midea", "inv")
    assert main.resolve_model_id("12K", " Midea ", "INV") == "mdl_000002"


def test_complete_model_summary(client):
    response = client.get("/modelos/mdl_000002/resumen")
    assert response.status_code == 200
    summary = response.json()
    assert set(summary["data_status"].values()) == {"available"}
    assert sorted(summary["specs"]) == ["L01", "L03"]


def test_partial_model_summary_and_missing_model(client):
    summary = client.get("/modelos/mdl_000001/resumen").json()
    assert summary["data_status"]["palletizacion"] == "available"
    assert summary["data_status"]["specs"] == "missing"
    assert summary["personal"] is None
    assert client.get("/modelos/mdl_999999/resumen").status_code == 404


def test_summary_reports_known_warnings(client):
    pallet_warning = client.get("/modelos/mdl_000014/resumen").json()
    assert pallet_warning["data_status"]["palletizacion"] == "warning"
    assert pallet_warning["warnings"]
    layout_warning = client.get("/modelos/mdl_000008/resumen").json()
    assert layout_warning["data_status"]["layout"] == "warning"


def test_integrity_report_identifies_orphans_and_ambiguities(client):
    report = client.get("/modelos/integridad").json()
    assert report["model_count"] == 20
    assert report["products_without_master_identity"] == []
    assert "9k/midea/inv" in report["specs_without_product"]
    assert "UC.SPL.F/C BSIC35WCLW" in report["duplicate_sku_references"]


def engineering_change_payload(**overrides):
    payload = {
        "change_type": "material_component",
        "title": "Cambio de material",
        "sector": "Tramo 2",
        "description": "Se reemplaza el material en la fijación superior.",
        "old_code": "273",
        "new_code": "263",
        "reason": "Disponibilidad validada por Ingeniería",
        "status": "active",
        "remind_next_production": True,
        "created_by": "Ingeniería",
        "notes": "Controlar durante el arranque",
    }
    payload.update(overrides)
    return payload


def test_history_initialization_creation_read_and_persistence(client):
    assert not main.HISTORY_DB_PATH.exists()
    response = client.post("/modelos/mdl_000002/cambios", json=engineering_change_payload(), headers=auth())
    assert response.status_code == 201
    change = response.json()
    assert change["change_id"] == "CHG-000001"
    assert change["model_id"] == "mdl_000002"
    assert change["remind_next_production"] is True
    assert change["created_at"] == change["updated_at"]
    assert main.HISTORY_DB_PATH.exists()
    assert client.get("/cambios/CHG-000001").json()["new_code"] == "263"
    main.initialize_history(main.HISTORY_DB_PATH)
    assert client.get("/modelos/mdl_000002/cambios").json()[0]["change_id"] == "CHG-000001"


def test_history_reads_are_public_and_writes_are_protected(client):
    assert client.get("/modelos/mdl_000002/cambios").status_code == 200
    assert client.post("/modelos/mdl_000002/cambios", json=engineering_change_payload()).status_code == 401
    assert client.post(
        "/modelos/mdl_000002/cambios", json=engineering_change_payload(), headers={"X-API-Key": "wrong"}
    ).status_code == 401
    created = client.post("/modelos/mdl_000002/cambios", json=engineering_change_payload(), headers=auth()).json()
    assert client.patch(f"/cambios/{created['change_id']}", json={"status": "closed"}).status_code == 401
    assert client.patch(
        f"/cambios/{created['change_id']}", json={"status": "closed"}, headers=auth()
    ).status_code == 200


def test_history_patch_is_allowed_by_cors(client):
    response = client.request(
        "OPTIONS",
        "/cambios/CHG-000001",
        headers={"Origin": "http://127.0.0.1:5500", "Access-Control-Request-Method": "PATCH"},
    )
    assert response.status_code == 200
    assert "PATCH" in response.headers["access-control-allow-methods"]


def test_history_rejects_unknown_model_and_invalid_payload(client):
    assert client.post(
        "/modelos/mdl_inexistente/cambios", json=engineering_change_payload(), headers=auth()
    ).status_code == 404
    assert client.post(
        "/modelos/mdl_000002/cambios", json=engineering_change_payload(change_type="invented"), headers=auth()
    ).status_code == 422
    assert client.post(
        "/modelos/mdl_000002/cambios", json=engineering_change_payload(title=" "), headers=auth()
    ).status_code == 422


def test_engineering_note_without_material_codes_is_valid(client):
    response = client.post(
        "/modelos/mdl_000002/cambios",
        json=engineering_change_payload(
            change_type="engineering_observation", old_code=None, new_code=None,
            title="Posición del sensor", description="Verificar alojamiento antes del cierre.",
        ),
        headers=auth(),
    )
    assert response.status_code == 201
    assert response.json()["old_code"] is None


def test_active_reminder_filters_and_closing_preserves_history(client):
    created = client.post(
        "/modelos/mdl_000002/cambios", json=engineering_change_payload(), headers=auth()
    ).json()
    reminders = client.get(
        "/modelos/mdl_000002/cambios?status=active&remind_next_production=true"
    ).json()
    assert [item["change_id"] for item in reminders] == [created["change_id"]]
    closed = client.patch(
        f"/cambios/{created['change_id']}", json={"status": "closed"}, headers=auth()
    ).json()
    assert closed["status"] == "closed"
    assert closed["remind_next_production"] is True
    assert client.get(
        "/modelos/mdl_000002/cambios?status=active&remind_next_production=true"
    ).json() == []
    assert len(client.get("/modelos/mdl_000002/cambios").json()) == 1


def test_changes_never_mix_between_models_and_are_recent_first(client):
    first = client.post(
        "/modelos/mdl_000002/cambios", json=engineering_change_payload(title="Cambio A"), headers=auth()
    ).json()
    second = client.post(
        "/modelos/mdl_000013/cambios", json=engineering_change_payload(title="Cambio B"), headers=auth()
    ).json()
    third = client.post(
        "/modelos/mdl_000002/cambios", json=engineering_change_payload(title="Cambio C"), headers=auth()
    ).json()
    model_a = client.get("/modelos/mdl_000002/cambios").json()
    model_b = client.get("/modelos/mdl_000013/cambios").json()
    assert [item["change_id"] for item in model_a] == [third["change_id"], first["change_id"]]
    assert [item["change_id"] for item in model_b] == [second["change_id"]]


def test_history_filters_and_configuration(client):
    client.post("/modelos/mdl_000002/cambios", json=engineering_change_payload(), headers=auth())
    client.post(
        "/modelos/mdl_000002/cambios",
        json=engineering_change_payload(change_type="process", status="evaluation", remind_next_production=False),
        headers=auth(),
    )
    assert len(client.get("/modelos/mdl_000002/cambios?change_type=process").json()) == 1
    assert len(client.get("/modelos/mdl_000002/cambios?status=evaluation").json()) == 1
    config = client.get("/cambios/configuracion").json()
    assert config["statuses"]["active"] == "Vigente"
    assert config["change_types"]["material_component"] == "Material / componente"


def test_history_schema_has_expected_indexes_and_is_idempotent(client):
    main.initialize_history(main.HISTORY_DB_PATH)
    main.initialize_history(main.HISTORY_DB_PATH)
    with sqlite3.connect(main.HISTORY_DB_PATH) as conn:
        columns = {row[1] for row in conn.execute("PRAGMA table_info(engineering_changes)")}
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(engineering_changes)")}
    assert {"id", "change_id", "model_id", "status", "created_at", "updated_at"} <= columns
    assert {"idx_changes_model_id", "idx_changes_status", "idx_changes_created_at", "idx_changes_model_reminder"} <= indexes


def test_change_id_and_creation_date_cannot_be_overwritten(client):
    payload = engineering_change_payload(change_id="CHG-999999", created_at="2000-01-01T00:00:00Z")
    assert client.post("/modelos/mdl_000002/cambios", json=payload, headers=auth()).status_code == 422
