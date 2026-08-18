import asyncio
import json
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
    monkeypatch.setenv("ADMIN_API_KEY", ADMIN_KEY)
    yield AsgiClient(main.app)


def auth():
    return {"X-API-Key": ADMIN_KEY}


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
