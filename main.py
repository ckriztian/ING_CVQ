import csv
import hmac
import io
import json
import logging
import os
import shutil
import tempfile
import unicodedata
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional

import pandas as pd
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Response, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field, HttpUrl, field_validator

logger = logging.getLogger("bgh_sistema_experto")
logging.basicConfig(level=os.getenv("LOG_LEVEL", "INFO"))

BASE_DIR = Path(__file__).resolve().parent
DATA_PATHS = {
    "palletizacion": BASE_DIR / "palletizacion.csv",
    "especificaciones": BASE_DIR / "especificaciones.csv",
    "personal": BASE_DIR / "personal_linea.json",
    "layouts": BASE_DIR / "layouts.json",
    "tiempos": BASE_DIR / "tiempos_linea.json",
    "modelos": BASE_DIR / "modelos.json",
}

# Alias conservados porque las pruebas y las operaciones administrativas aíslan
# cada fuente sustituyendo su ruta. Todas las rutas, incluido MODELOS_PATH, se
# crean juntas antes de cargar cualquier archivo durante la importación Uvicorn.
CSV_PATH = DATA_PATHS["palletizacion"]
ESPEC_PATH = DATA_PATHS["especificaciones"]
PERSONAL_PATH = DATA_PATHS["personal"]
LAYOUTS_PATH = DATA_PATHS["layouts"]
TIEMPOS_PATH = DATA_PATHS["tiempos"]
MODELOS_PATH = DATA_PATHS["modelos"]

PALLET_COLUMNS = [
    "capacidad", "proveedor", "modelo", "unidades_por_pallet", "capas",
    "cajas_por_capa", "dim_pallet_l_mm", "dim_pallet_a_mm", "dim_pallet_h_mm",
    "peso_unitario_kg", "peso_max_pallet_kg", "apilable_hasta", "orientacion",
    "embalaje", "sku", "notas",
]
SPEC_COLUMNS = [
    "capacidad", "proveedor", "modelo", "linea", "btus", "consumo_w",
    "eficiencia_seer", "ruido_ui_db", "ruido_ue_db", "ui_dim_mm_l",
    "ui_dim_mm_a", "ui_dim_mm_h", "ue_dim_mm_l", "ue_dim_mm_a",
    "ue_dim_mm_h", "refrigerante", "nota",
]


def configured_origins() -> List[str]:
    raw = os.getenv("ALLOWED_ORIGINS", "http://127.0.0.1:5500,http://localhost:5500,null")
    return [origin.strip() for origin in raw.split(",") if origin.strip()]


app = FastAPI(title="BGH · Ingeniería AA — Sistema Experto AC", version="2.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=configured_origins(),
    allow_credentials=False,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-API-Key"],
)


def norm(value: Optional[str]) -> str:
    if value is None:
        return ""
    value = unicodedata.normalize("NFKD", value.strip().lower())
    return "".join(ch for ch in value if not unicodedata.combining(ch))


def to_int(value: Any, default: Optional[int] = None) -> Optional[int]:
    try:
        return int(float(str(value).replace(",", ".")))
    except (TypeError, ValueError):
        return default


def to_float(value: Any, default: Optional[float] = None) -> Optional[float]:
    try:
        return float(str(value).replace(",", "."))
    except (TypeError, ValueError):
        return default


def model_key(capacidad: str, proveedor: str, modelo: str) -> str:
    return f"{norm(capacidad)}_{norm(proveedor)}_{norm(modelo)}"


def require_positive(value: Optional[float], field: str, row_number: int, *, zero_allowed: bool = False) -> None:
    invalid = value is None or value < 0 if zero_allowed else value is None or value <= 0
    if invalid:
        operator = ">= 0" if zero_allowed else "> 0"
        raise ValueError(f"Fila {row_number}: {field} debe ser {operator}")


def load_knowledge(csv_path: Path) -> Dict[str, Any]:
    if not csv_path.exists():
        raise FileNotFoundError(f"No existe el archivo de palletización: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = set(PALLET_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas de palletización: {', '.join(sorted(missing))}")
    kb: Dict[str, Any] = {}
    for index, row in df.iterrows():
        row_number = index + 2
        cap, prov, mod = norm(row["capacidad"]), norm(row["proveedor"]), norm(row["modelo"])
        if not cap or not prov or not mod:
            raise ValueError(f"Fila {row_number}: capacidad, proveedor y modelo son obligatorios")
        units = to_int(row["unidades_por_pallet"])
        layers = to_int(row["capas"])
        boxes = to_int(row["cajas_por_capa"])
        dimensions = [to_int(row[name]) for name in ("dim_pallet_l_mm", "dim_pallet_a_mm", "dim_pallet_h_mm")]
        unit_weight = to_float(row["peso_unitario_kg"])
        max_weight = to_float(row["peso_max_pallet_kg"])
        stackable = to_int(row["apilable_hasta"])
        for value, name in [(units, "unidades_por_pallet"), (layers, "capas"), (boxes, "cajas_por_capa"), (stackable, "apilable_hasta")]:
            require_positive(value, name, row_number)
        for value, name in zip(dimensions, ("dim_pallet_l_mm", "dim_pallet_a_mm", "dim_pallet_h_mm")):
            require_positive(value, name, row_number)
        require_positive(unit_weight, "peso_unitario_kg", row_number, zero_allowed=True)
        require_positive(max_weight, "peso_max_pallet_kg", row_number, zero_allowed=True)
        if units != layers * boxes:
            logger.warning(
                "Validación industrial pendiente en fila %s: unidades_por_pallet=%s no coincide con capas*cajas_por_capa=%s. Requiere validación de Ingeniería/Logística.",
                row_number, units, layers * boxes,
            )
        record = {
            "unidades_por_pallet": units, "capas": layers, "cajas_por_capa": boxes,
            "dim_pallet_mm": dimensions, "peso_unitario_kg": unit_weight,
            "peso_max_pallet_kg": max_weight, "apilable_hasta": stackable,
            "orientacion": row["orientacion"].strip(), "embalaje": row["embalaje"].strip(),
            "sku": row["sku"].strip(), "notas": row["notas"].strip(),
        }
        if mod in kb.setdefault(cap, {}).setdefault(prov, {}):
            raise ValueError(f"Fila {row_number}: clave de modelo duplicada {cap}/{prov}/{mod}")
        kb[cap][prov][mod] = record
    return kb


def load_specs(csv_path: Path) -> Dict[str, Any]:
    if not csv_path.exists():
        raise FileNotFoundError(f"No existe el archivo de especificaciones: {csv_path}")
    df = pd.read_csv(csv_path, dtype=str, keep_default_na=False)
    missing = set(SPEC_COLUMNS) - set(df.columns)
    if missing:
        raise ValueError(f"Faltan columnas de especificaciones: {', '.join(sorted(missing))}")
    specs: Dict[str, Any] = {}
    numeric_fields = ["btus", "consumo_w", "eficiencia_seer", "ruido_ui_db", "ruido_ue_db", "ui_dim_mm_l", "ui_dim_mm_a", "ui_dim_mm_h", "ue_dim_mm_l", "ue_dim_mm_a", "ue_dim_mm_h"]
    for index, row in df.iterrows():
        row_number = index + 2
        cap, prov, mod, line = map(norm, [row["capacidad"], row["proveedor"], row["modelo"], row["linea"]])
        if not all((cap, prov, mod, line)):
            raise ValueError(f"Fila {row_number}: capacidad, proveedor, modelo y línea son obligatorios")
        for field in numeric_fields:
            require_positive(to_float(row[field]), field, row_number)
        record = {
            "btus": row["btus"], "consumo_w": row["consumo_w"], "eficiencia_seer": row["eficiencia_seer"],
            "ruido_ui_db": row["ruido_ui_db"], "ruido_ue_db": row["ruido_ue_db"],
            "ui_dim_mm": [row["ui_dim_mm_l"], row["ui_dim_mm_a"], row["ui_dim_mm_h"]],
            "ue_dim_mm": [row["ue_dim_mm_l"], row["ue_dim_mm_a"], row["ue_dim_mm_h"]],
            "refrigerante": row["refrigerante"].strip(), "nota": row["nota"].strip(),
        }
        lines = specs.setdefault(cap, {}).setdefault(prov, {}).setdefault(mod, {})
        if line in lines:
            raise ValueError(f"Fila {row_number}: especificación duplicada para {cap}/{prov}/{mod}/{line}")
        lines[line] = record
    return specs


def load_json(path: Path, label: str) -> Dict[str, Any]:
    if not path.exists():
        logger.warning("No existe %s (%s); se inicia sin registros.", label, path)
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        logger.error("JSON inválido en %s (%s): %s. El archivo se conserva y no debe sobrescribirse.", label, path, exc)
        raise RuntimeError(f"{label} contiene JSON inválido") from exc
    except OSError as exc:
        logger.error("No se pudo leer %s (%s): %s", label, path, exc)
        raise RuntimeError(f"No se pudo leer {label}") from exc
    if not isinstance(data, dict):
        raise RuntimeError(f"{label} debe contener un objeto JSON")
    return data


def load_models(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(f"No existe el catálogo maestro: {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise RuntimeError("El catálogo maestro contiene JSON inválido") from exc
    except OSError as exc:
        raise RuntimeError("No se pudo leer el catálogo maestro") from exc
    if not isinstance(data, list):
        raise RuntimeError("El catálogo maestro debe contener una lista JSON")
    ids, keys = set(), set()
    for index, item in enumerate(data, 1):
        if not isinstance(item, dict):
            raise RuntimeError(f"Modelo {index}: se esperaba un objeto")
        model_id = item.get("model_id")
        key = tuple(norm(item.get(field)) for field in ("capacidad", "proveedor", "modelo"))
        if not isinstance(model_id, str) or not model_id.startswith("mdl_") or not all(key):
            raise RuntimeError(f"Modelo {index}: identidad incompleta o model_id inválido")
        if model_id in ids:
            raise RuntimeError(f"model_id duplicado: {model_id}")
        if key in keys:
            raise RuntimeError(f"Clave de producto duplicada: {'/'.join(key)}")
        ids.add(model_id)
        keys.add(key)
    return data


def atomic_write_text(path: Path, text: str, validator) -> None:
    validator(text)
    path.parent.mkdir(parents=True, exist_ok=True)
    backup = path.with_suffix(path.suffix + ".bak")
    if path.exists():
        validator(path.read_text(encoding="utf-8"))
        shutil.copy2(path, backup)
    fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", suffix=".tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="") as handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    except Exception:
        try:
            os.unlink(temp_name)
        except FileNotFoundError:
            pass
        raise


def atomic_save_json(path: Path, data: Dict[str, Any]) -> None:
    text = json.dumps(data, ensure_ascii=False, indent=2) + "\n"
    atomic_write_text(path, text, json.loads)


def validate_csv_text(text: str, expected_columns: List[str], loader, target: Path) -> None:
    reader = csv.reader(io.StringIO(text))
    try:
        header = next(reader)
    except StopIteration as exc:
        raise ValueError("El CSV está vacío") from exc
    if header != expected_columns:
        raise ValueError("Las columnas del CSV no coinciden con el esquema esperado")
    fd, name = tempfile.mkstemp(suffix=".csv", dir=target.parent)
    os.close(fd)
    temp = Path(name)
    try:
        temp.write_text(text, encoding="utf-8")
        loader(temp)
    finally:
        temp.unlink(missing_ok=True)


def save_csv(path: Path, text: str, columns: List[str], loader) -> None:
    validator = lambda candidate: validate_csv_text(candidate, columns, loader, path)
    atomic_write_text(path, text.rstrip("\n") + "\n", validator)


KB = load_knowledge(CSV_PATH)
SPECS = load_specs(ESPEC_PATH)
PERSONAL = load_json(PERSONAL_PATH, "personal de línea")
LAYOUTS = load_json(LAYOUTS_PATH, "layouts")
TIEMPOS = load_json(TIEMPOS_PATH, "tiempos de línea")
# La carga crítica no depende del alias global MODELOS_PATH. Esto también hace
# segura la importación en el subproceso que crea Uvicorn --reload en Windows,
# aun cuando herramientas de sincronización apliquen parcialmente el bloque de
# aliases. BASE_DIR siempre se define antes de ejecutar esta línea.
MODELOS = load_models(BASE_DIR / "modelos.json")
MODELS_BY_ID = {item["model_id"]: item for item in MODELOS}
MODEL_ID_BY_KEY = {
    (norm(item["capacidad"]), norm(item["proveedor"]), norm(item["modelo"])): item["model_id"]
    for item in MODELOS
}


class PalletInfo(BaseModel):
    unidades_por_pallet: int = Field(gt=0)
    capas: int = Field(gt=0)
    cajas_por_capa: int = Field(gt=0)
    dim_pallet_mm: List[int]
    peso_unitario_kg: Optional[float] = Field(default=None, ge=0)
    peso_max_pallet_kg: Optional[float] = Field(default=None, ge=0)
    apilable_hasta: Optional[int] = Field(default=None, gt=0)
    orientacion: Optional[str] = None
    embalaje: Optional[str] = None
    sku: Optional[str] = None
    notas: Optional[str] = None


class CatalogoItem(BaseModel):
    capacidad: str
    proveedor: str
    modelo: str


class CalculoRequest(BaseModel):
    capacidad: str = Field(min_length=1, max_length=80)
    proveedor: str = Field(min_length=1, max_length=80)
    modelo: str = Field(min_length=1, max_length=120)
    cantidad: int = Field(gt=0, le=10_000_000)


class CalculoResult(BaseModel):
    capacidad: str
    proveedor: str
    modelo: str
    cantidad: int
    unidades_por_pallet: int
    pallets_completos: int
    resto: int
    pallets_totales: int
    alerta_altura: bool
    alerta_peso: bool


class Tramo(BaseModel):
    nombre: str = Field(min_length=1, max_length=120)
    personas: int = Field(ge=0, le=999)


class PersonalLinea(BaseModel):
    nombre_modelo: Optional[str] = Field(default=None, max_length=200)
    ot: Optional[str] = Field(default=None, max_length=100)
    pnb: Optional[str] = Field(default=None, max_length=100)
    tramos: List[Tramo] = Field(default_factory=list, max_length=100)


class LayoutItem(BaseModel):
    nombre: Optional[str] = Field(default=None, max_length=200)
    url: HttpUrl
    descripcion: Optional[str] = Field(default=None, max_length=500)
    estado: Optional[str] = Field(default=None, max_length=50)
    version: Optional[str] = Field(default=None, max_length=50)
    fecha: Optional[str] = Field(default=None, max_length=30)


class TiemposItem(BaseModel):
    titulo: str = Field(default="Distribución de tiempos por puesto", min_length=1, max_length=200)
    limite: float = Field(gt=0, le=100_000)
    tiempos: List[float] = Field(min_length=1, max_length=500)

    @field_validator("tiempos")
    @classmethod
    def validate_times(cls, values: List[float]) -> List[float]:
        if any(value < 0 or value > 100_000 for value in values):
            raise ValueError("Los tiempos deben estar entre 0 y 100000 segundos")
        return values


class CsvReplaceRequest(BaseModel):
    csv_text: str = Field(min_length=1, max_length=5_000_000)


class MasterModel(BaseModel):
    model_id: str
    capacidad: str
    proveedor: str
    modelo: str
    sku_bgh: Optional[str] = None
    pnb: Optional[str] = None


def require_admin(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")) -> bool:
    configured_key = os.getenv("ADMIN_API_KEY")
    if not configured_key:
        logger.warning("Operación administrativa bloqueada: ADMIN_API_KEY no está configurada.")
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "Administración deshabilitada: ADMIN_API_KEY no configurada")
    if not x_api_key or not hmac.compare_digest(x_api_key, configured_key):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "API Key inválida")
    return True


def require_catalog_model(capacidad: str, proveedor: str, modelo: str) -> None:
    if not KB.get(norm(capacidad), {}).get(norm(proveedor), {}).get(norm(modelo)):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Modelo no encontrado en el catálogo")


def resolve_model(model_id: str) -> Dict[str, Any]:
    identity = MODELS_BY_ID.get(model_id)
    if not identity:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "model_id no encontrado")
    return identity


def resolve_model_id(capacidad: str, proveedor: str, modelo: str) -> Optional[str]:
    return MODEL_ID_BY_KEY.get((norm(capacidad), norm(proveedor), norm(modelo)))


def valid_iso_date(value: Any) -> bool:
    if not value:
        return True
    try:
        date.fromisoformat(str(value))
        return True
    except ValueError:
        return False


def model_summary(identity: Dict[str, Any]) -> Dict[str, Any]:
    cap, prov, mod = (norm(identity[field]) for field in ("capacidad", "proveedor", "modelo"))
    key = model_key(cap, prov, mod)
    pallet = KB.get(cap, {}).get(prov, {}).get(mod)
    specs = SPECS.get(cap, {}).get(prov, {}).get(mod)
    personal = PERSONAL.get(key)
    layout = LAYOUTS.get(key)
    tiempos = TIEMPOS.get(key)
    pallet_warning = bool(pallet and pallet["unidades_por_pallet"] != pallet["capas"] * pallet["cajas_por_capa"])
    layout_warning = bool(layout and not valid_iso_date(layout.get("fecha")))
    return {
        "model_id": identity["model_id"],
        "identity": identity,
        "data_status": {
            "palletizacion": "warning" if pallet_warning else "available" if pallet else "missing",
            "specs": "available" if specs else "missing",
            "personal": "available" if personal else "missing",
            "layout": "warning" if layout_warning else "available" if layout else "missing",
            "tiempos": "available" if tiempos else "missing",
        },
        "palletizacion": pallet,
        "specs": {line.upper(): value for line, value in (specs or {}).items()} or None,
        "personal": personal,
        "layout": layout,
        "tiempos": tiempos,
        "warnings": [
            message for condition, message in [
                (pallet_warning, "La configuración de pallet no coincide con capas × cajas por capa; requiere validación de Ingeniería/Logística."),
                (layout_warning, "La fecha del layout no tiene un formato ISO válido; requiere validación humana."),
            ] if condition
        ],
    }


def integrity_report() -> Dict[str, Any]:
    pallet_keys = {(cap, prov, mod) for cap, providers in KB.items() for prov, models in providers.items() for mod in models}
    spec_keys = {(cap, prov, mod) for cap, providers in SPECS.items() for prov, models in providers.items() for mod in models}
    master_keys = set(MODEL_ID_BY_KEY)
    json_keys = {
        "personal": set(PERSONAL), "layout": set(LAYOUTS), "tiempos": set(TIEMPOS),
    }
    key_label = lambda key: "/".join(key)
    master_json_keys = {model_key(*key) for key in master_keys}
    duplicate_skus: Dict[str, List[str]] = {}
    for item in MODELOS:
        sku = item.get("sku_bgh")
        if sku:
            duplicate_skus.setdefault(sku, []).append(item["model_id"])
    return {
        "model_count": len(MODELOS),
        "products_without_master_identity": sorted(key_label(key) for key in pallet_keys - master_keys),
        "master_models_without_pallet": sorted(key_label(key) for key in master_keys - pallet_keys),
        "specs_without_product": sorted(key_label(key) for key in spec_keys - pallet_keys),
        "products_without_specs": sorted(key_label(key) for key in pallet_keys - spec_keys),
        "products_without_personal": sorted(key_label(key) for key in master_keys if model_key(*key) not in json_keys["personal"]),
        "products_without_layout": sorted(key_label(key) for key in master_keys if model_key(*key) not in json_keys["layout"]),
        "products_without_tiempos": sorted(key_label(key) for key in master_keys if model_key(*key) not in json_keys["tiempos"]),
        "orphan_personal_keys": sorted(json_keys["personal"] - master_json_keys),
        "orphan_layout_keys": sorted(json_keys["layout"] - master_json_keys),
        "orphan_tiempos_keys": sorted(json_keys["tiempos"] - master_json_keys),
        "duplicate_sku_references": {sku: ids for sku, ids in duplicate_skus.items() if len(ids) > 1},
        "models_with_warnings": [item["model_id"] for item in MODELOS if "warning" in model_summary(item)["data_status"].values()],
    }


@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}


@app.get("/catalogo", response_model=List[CatalogoItem])
def catalogo():
    return [{"capacidad": cap, "proveedor": prov, "modelo": mod} for cap, provs in KB.items() for prov, mods in provs.items() for mod in mods]


@app.get("/lineas", response_model=List[str])
def lineas():
    return sorted({line.upper() for capacities in SPECS.values() for providers in capacities.values() for models in providers.values() for line in models})


@app.get("/modelos", response_model=List[MasterModel])
def get_models():
    return MODELOS


@app.get("/modelos/integridad")
def get_integrity_report():
    return integrity_report()


@app.get("/modelos/{model_id}", response_model=MasterModel)
def get_model(model_id: str):
    return resolve_model(model_id)


@app.get("/modelos/{model_id}/resumen")
def get_model_summary(model_id: str):
    return model_summary(resolve_model(model_id))


@app.get("/pallets", response_model=PalletInfo)
def pallets(capacidad: str = Query(...), proveedor: str = Query(...), modelo: str = Query(...)):
    result = KB.get(norm(capacidad), {}).get(norm(proveedor), {}).get(norm(modelo))
    if not result:
        raise HTTPException(404, "No hay configuración para esa combinación")
    return result


@app.post("/calcular-pallets", response_model=CalculoResult)
def calcular_pallets(req: CalculoRequest):
    cap, prov, mod = norm(req.capacidad), norm(req.proveedor), norm(req.modelo)
    info = KB.get(cap, {}).get(prov, {}).get(mod)
    if not info:
        raise HTTPException(404, "Modelo no encontrado")
    units = info["unidades_por_pallet"]
    complete, remainder = divmod(req.cantidad, units)
    height = info["dim_pallet_mm"][2]
    return CalculoResult(
        capacidad=cap, proveedor=prov, modelo=mod, cantidad=req.cantidad,
        unidades_por_pallet=units, pallets_completos=complete, resto=remainder,
        pallets_totales=complete + bool(remainder),
        alerta_altura=height * (info.get("apilable_hasta") or 1) > 1850,
        alerta_peso=(info.get("peso_unitario_kg") or 0) * units > (info.get("peso_max_pallet_kg") or float("inf")),
    )


@app.get("/specs")
def get_specs(capacidad: str, proveedor: str, modelo: str, linea: str):
    result = SPECS.get(norm(capacidad), {}).get(norm(proveedor), {}).get(norm(modelo), {}).get(norm(linea))
    if not result:
        raise HTTPException(404, "Especificaciones no encontradas")
    return result


@app.get("/personal", response_model=PersonalLinea)
def get_personal(capacidad: str, proveedor: str, modelo: str):
    require_catalog_model(capacidad, proveedor, modelo)
    key = model_key(capacidad, proveedor, modelo)
    if key not in PERSONAL:
        raise HTTPException(404, "No existe información de personal registrada")
    return PERSONAL[key]


@app.post("/personal", dependencies=[Depends(require_admin)])
def set_personal(capacidad: str, proveedor: str, modelo: str, body: PersonalLinea):
    require_catalog_model(capacidad, proveedor, modelo)
    PERSONAL[model_key(capacidad, proveedor, modelo)] = body.model_dump()
    atomic_save_json(PERSONAL_PATH, PERSONAL)
    return {"status": "saved", "key": model_key(capacidad, proveedor, modelo)}


@app.get("/layouts", response_model=LayoutItem)
def get_layout(capacidad: str, proveedor: str, modelo: str):
    require_catalog_model(capacidad, proveedor, modelo)
    result = LAYOUTS.get(model_key(capacidad, proveedor, modelo))
    if not result:
        raise HTTPException(404, "No existe un layout registrado")
    return result


@app.put("/layouts", dependencies=[Depends(require_admin)])
def put_layout(capacidad: str, proveedor: str, modelo: str, body: LayoutItem):
    require_catalog_model(capacidad, proveedor, modelo)
    LAYOUTS[model_key(capacidad, proveedor, modelo)] = body.model_dump(mode="json")
    atomic_save_json(LAYOUTS_PATH, LAYOUTS)
    return {"status": "saved", "key": model_key(capacidad, proveedor, modelo)}


@app.delete("/layouts", status_code=204, dependencies=[Depends(require_admin)])
def delete_layout(capacidad: str, proveedor: str, modelo: str):
    key = model_key(capacidad, proveedor, modelo)
    if key not in LAYOUTS:
        raise HTTPException(404, "No existe un layout registrado")
    del LAYOUTS[key]
    atomic_save_json(LAYOUTS_PATH, LAYOUTS)
    return Response(status_code=204)


@app.get("/tiempos", response_model=TiemposItem)
def get_tiempos(capacidad: str, proveedor: str, modelo: str):
    require_catalog_model(capacidad, proveedor, modelo)
    result = TIEMPOS.get(model_key(capacidad, proveedor, modelo))
    if not result:
        raise HTTPException(404, "No existen tiempos registrados")
    return result


@app.put("/tiempos", dependencies=[Depends(require_admin)])
def put_tiempos(capacidad: str, proveedor: str, modelo: str, body: TiemposItem):
    require_catalog_model(capacidad, proveedor, modelo)
    if any(value < 0 or value > 100_000 for value in body.tiempos):
        raise HTTPException(422, "Los tiempos deben estar entre 0 y 100000 segundos")
    TIEMPOS[model_key(capacidad, proveedor, modelo)] = body.model_dump()
    atomic_save_json(TIEMPOS_PATH, TIEMPOS)
    return {"status": "saved", "key": model_key(capacidad, proveedor, modelo)}


@app.delete("/tiempos", status_code=204, dependencies=[Depends(require_admin)])
def delete_tiempos(capacidad: str, proveedor: str, modelo: str):
    key = model_key(capacidad, proveedor, modelo)
    if key not in TIEMPOS:
        raise HTTPException(404, "No existen tiempos registrados")
    del TIEMPOS[key]
    atomic_save_json(TIEMPOS_PATH, TIEMPOS)
    return Response(status_code=204)


@app.get("/admin/verify", dependencies=[Depends(require_admin)])
def verify_admin():
    return {"status": "authorized"}


@app.get("/admin/csv", response_class=PlainTextResponse, dependencies=[Depends(require_admin)])
def admin_csv():
    return CSV_PATH.read_text(encoding="utf-8")


@app.post("/admin/csv/replace", dependencies=[Depends(require_admin)])
def replace_csv(body: CsvReplaceRequest):
    global KB
    try:
        save_csv(CSV_PATH, body.csv_text, PALLET_COLUMNS, load_knowledge)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    KB = load_knowledge(CSV_PATH)
    return {"status": "saved", "rows": len(catalogo())}


@app.get("/admin/specs", response_class=PlainTextResponse, dependencies=[Depends(require_admin)])
def admin_specs():
    return ESPEC_PATH.read_text(encoding="utf-8")


@app.post("/admin/specs/replace", dependencies=[Depends(require_admin)])
def replace_specs(body: CsvReplaceRequest):
    global SPECS
    try:
        save_csv(ESPEC_PATH, body.csv_text, SPEC_COLUMNS, load_specs)
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    SPECS = load_specs(ESPEC_PATH)
    return {"status": "saved"}


@app.post("/reload", dependencies=[Depends(require_admin)])
def reload_all():
    global KB, SPECS, PERSONAL, LAYOUTS, TIEMPOS, MODELOS, MODELS_BY_ID, MODEL_ID_BY_KEY
    KB, SPECS = load_knowledge(CSV_PATH), load_specs(ESPEC_PATH)
    PERSONAL = load_json(PERSONAL_PATH, "personal de línea")
    LAYOUTS = load_json(LAYOUTS_PATH, "layouts")
    TIEMPOS = load_json(TIEMPOS_PATH, "tiempos de línea")
    MODELOS = load_models(BASE_DIR / "modelos.json")
    MODELS_BY_ID = {item["model_id"]: item for item in MODELOS}
    MODEL_ID_BY_KEY = {
        (norm(item["capacidad"]), norm(item["proveedor"]), norm(item["modelo"])): item["model_id"]
        for item in MODELOS
    }
    return {"status": "all_reloaded"}


@app.post("/reload-specs", dependencies=[Depends(require_admin)])
def reload_specs():
    global SPECS
    SPECS = load_specs(ESPEC_PATH)
    return {"status": "specs_reloaded"}


@app.post("/reload-layouts", dependencies=[Depends(require_admin)])
def reload_layouts():
    global LAYOUTS
    LAYOUTS = load_json(LAYOUTS_PATH, "layouts")
    return {"status": "layouts_reloaded", "rows": len(LAYOUTS)}


@app.post("/reload-tiempos", dependencies=[Depends(require_admin)])
def reload_tiempos():
    global TIEMPOS
    TIEMPOS = load_json(TIEMPOS_PATH, "tiempos de línea")
    return {"status": "tiempos_reloaded", "rows": len(TIEMPOS)}


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
