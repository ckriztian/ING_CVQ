from fastapi import FastAPI, HTTPException, Query, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import PlainTextResponse
from pydantic import BaseModel, Field
from typing import Dict, Any, List, Optional
import pandas as pd
import matplotlib
# Forzamos el backend no interactivo antes de importar pyplot
matplotlib.use('Agg') 
from matplotlib import pyplot as plt
from pathlib import Path
import unicodedata
import os
import json

# =============================
# Archivos de datos
# =============================
CSV_PATH = Path("palletizacion.csv")
ESPEC_PATH = Path("especificaciones.csv")
PERSONAL_PATH = Path("personal_linea.json")
LAYOUTS_PATH = Path("layouts.json")

# =============================
# App
# =============================
app = FastAPI(title="BGH · Ingeniería AA — Sistema Experto AC", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# =============================
# Utilidades
# =============================

def norm(s: str) -> str:
    if s is None:
        return ""
    s = s.strip().lower()
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return s

def to_int(x, default=None):
    try:
        return int(float(str(x).replace(",", ".")))
    except Exception:
        return default

def to_float(x, default=None):
    try:
        return float(str(x).replace(",", "."))
    except Exception:
        return default

def generar_grafico_tiempos(puestos, tiempos, titulo="Distribución de tiempos", limite=10, nombre_archivo="grafico_salida.png"):
    """
    Crea un gráfico de barras donde el exceso se pinta de rojo y lo guarda en disco.
    """
    try:
        tiempo_base = [min(t, limite) for t in tiempos]
        tiempo_exceso = [max(0, t - limite) for t in tiempos]

        fig = plt.figure(figsize=(10, 5))

        plt.bar(puestos, tiempo_base, color='blue', label=f'Hasta {limite}s')
        plt.bar(puestos, tiempo_exceso, bottom=tiempo_base, color='red', label='Exceso')
        plt.axhline(y=limite, color='black', linestyle='--', alpha=0.6)

        plt.xlabel("Puesto")
        plt.ylabel("Tiempo (segundos)")
        plt.title(titulo)
        plt.xticks(puestos)
        
        max_y = int(max(tiempos) + 2) if tiempos else 20
        plt.yticks(range(0, max_y, 1))
        
        plt.grid(axis='y', linestyle='--', alpha=0.5)
        plt.legend()
        
        if not nombre_archivo.endswith('.png'):
            nombre_archivo += '.png'
            
        plt.savefig(nombre_archivo, dpi=300, bbox_inches='tight')
        plt.close(fig) # Importante para liberar memoria en el servidor
        return True
    except Exception as e:
        print(f"Error generando gráfico: {e}")
        return False

# =============================
# Carga de Datos
# =============================

def load_knowledge(csv_path: Path) -> Dict:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path, dtype=str)
    kb: Dict = {}
    for _, r in df.iterrows():
        cap, prov, mod = norm(r["capacidad"]), norm(r["proveedor"]), norm(r["modelo"])
        record = {
            "unidades_por_pallet": to_int(r["unidades_por_pallet"]),
            "capas": to_int(r["capas"]),
            "cajas_por_capa": to_int(r["cajas_por_capa"]),
            "dim_pallet_mm": [to_int(r["dim_pallet_l_mm"]), to_int(r["dim_pallet_a_mm"]), to_int(r["dim_pallet_h_mm"])],
            "peso_unitario_kg": to_float(r["peso_unitario_kg"]),
            "peso_max_pallet_kg": to_float(r["peso_max_pallet_kg"]),
            "apilable_hasta": to_int(r["apilable_hasta"]),
            "orientacion": str(r["orientacion"]).strip(),
            "embalaje": str(r["embalaje"]).strip(),
            "sku": str(r["sku"]).strip(),
            "notas": str(r["notas"]).strip(),
        }
        kb.setdefault(cap, {}).setdefault(prov, {})[mod] = record
    return kb

def load_specs(csv_path: Path) -> Dict:
    if not csv_path.exists():
        return {}
    df = pd.read_csv(csv_path, dtype=str)
    specs: Dict = {}
    for _, r in df.iterrows():
        cap, prov, mod, lin = norm(r["capacidad"]), norm(r["proveedor"]), norm(r["modelo"]), norm(r["linea"])
        record = {
            "btus": r["btus"], "consumo_w": r["consumo_w"], "eficiencia_seer": r["eficiencia_seer"],
            "ruido_ui_db": r["ruido_ui_db"], "ruido_ue_db": r["ruido_ue_db"],
            "ui_dim_mm": [r["ui_dim_mm_l"], r["ui_dim_mm_a"], r["ui_dim_mm_h"]],
            "ue_dim_mm": [r["ue_dim_mm_l"], r["ue_dim_mm_a"], r["ue_dim_mm_h"]],
            "refrigerante": r["refrigerante"], "nota": r["nota"],
        }
        specs.setdefault(cap, {}).setdefault(prov, {}).setdefault(mod, {})[lin] = record
    return specs

def load_personal() -> Dict:
    if not PERSONAL_PATH.exists(): return {}
    try: return json.loads(PERSONAL_PATH.read_text(encoding="utf-8"))
    except: return {}

def save_personal(data: Dict):
    PERSONAL_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

def load_layouts() -> Dict:
    if not LAYOUTS_PATH.exists(): return {}
    try: return json.loads(LAYOUTS_PATH.read_text(encoding="utf-8"))
    except: return {}

def save_layouts(data: Dict):
    LAYOUTS_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")

# Carga inicial
KB = load_knowledge(CSV_PATH)
SPECS = load_specs(ESPEC_PATH)
PERSONAL = load_personal()
LAYOUTS = load_layouts()

# =============================
# Modelos Pydantic
# =============================

class PalletInfo(BaseModel):
    unidades_por_pallet: int
    capas: int
    cajas_por_capa: int
    dim_pallet_mm: List[int]
    peso_unitario_kg: Optional[float] = None
    peso_max_pallet_kg: Optional[float] = None
    apilable_hasta: Optional[int] = None
    orientacion: Optional[str] = None
    embalaje: Optional[str] = None
    sku: Optional[str] = None
    notas: Optional[str] = None

class CatalogoItem(BaseModel):
    capacidad: str
    proveedor: str
    modelo: str

class CalculoRequest(BaseModel):
    capacidad: str
    proveedor: str
    modelo: str
    cantidad: int = Field(..., gt=0)

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
    nombre: str
    personas: int

class PersonalLinea(BaseModel):
    nombre_modelo: Optional[str] = None
    ot: Optional[str] = None
    pnb: Optional[str] = None
    tramos: List[Tramo] = []

class LayoutItem(BaseModel):
    nombre: Optional[str] = None
    url: str
    descripcion: Optional[str] = None
    estado: Optional[str] = None
    version: Optional[str] = None
    fecha: Optional[str] = None

# =============================
# Endpoints
# =============================

@app.get("/health")
def health():
    return {"status": "ok", "version": app.version}

@app.get("/catalogo", response_model=List[CatalogoItem])
def catalogo():
    items = []
    for cap, provs in KB.items():
        for prov, mods in provs.items():
            for mod in mods:
                items.append({"capacidad": cap, "proveedor": prov, "modelo": mod})
    return items

@app.get("/pallets", response_model=PalletInfo)
def pallets(capacidad: str = Query(...), proveedor: str = Query(...), modelo: str = Query(...)):
    cap, prov, mod = norm(capacidad), norm(proveedor), norm(modelo)
    res = KB.get(cap, {}).get(prov, {}).get(mod)
    if not res:
        raise HTTPException(404, "No hay configuración para esa combinación")
    return res

@app.post("/calcular-pallets", response_model=CalculoResult)
def calcular_pallets(req: CalculoRequest):
    cap, prov, mod = norm(req.capacidad), norm(req.proveedor), norm(req.modelo)
    info = KB.get(cap, {}).get(prov, {}).get(mod)
    if not info:
        raise HTTPException(404, "Modelo no encontrado")

    up = info["unidades_por_pallet"]
    pallets_completos = req.cantidad // up
    resto = req.cantidad % up
    pallets_totales = pallets_completos + (1 if resto > 0 else 0)

    h_mm = (info.get("dim_pallet_mm") or [0,0,0])[2]
    apilable = info.get("apilable_hasta") or 1
    alerta_altura = (h_mm * apilable) > 1850
    alerta_peso = (info.get("peso_unitario_kg", 0) * up) > (info.get("peso_max_pallet_kg") or 99999)

    return CalculoResult(
        capacidad=cap, proveedor=prov, modelo=mod, cantidad=req.cantidad,
        unidades_por_pallet=up, pallets_completos=pallets_completos, resto=resto,
        pallets_totales=pallets_totales, alerta_altura=alerta_altura, alerta_peso=alerta_peso
    )

@app.get("/specs")
def get_specs(capacidad: str, proveedor: str, modelo: str, linea: str):
    cap, prov, mod, lin = map(norm, [capacidad, proveedor, modelo, linea])
    res = SPECS.get(cap, {}).get(prov, {}).get(mod, {}).get(lin)
    if not res:
        raise HTTPException(404, "Especificaciones no encontradas")
    return res

# ======== PERSONAL DE LÍNEA ========

@app.get("/personal", response_model=PersonalLinea)
def get_personal(capacidad: str, proveedor: str, modelo: str):
    key = f"{norm(capacidad)}_{norm(proveedor)}_{norm(modelo)}"
    if key not in PERSONAL:
        return PersonalLinea(tramos=[Tramo(nombre=f"Tramo {i}", personas=2) for i in range(1, 5)])
    return PERSONAL[key]

@app.post("/personal")
def set_personal(capacidad: str, proveedor: str, modelo: str, body: PersonalLinea):
    key = f"{norm(capacidad)}_{norm(proveedor)}_{norm(modelo)}"
    PERSONAL[key] = body.model_dump()
    save_personal(PERSONAL)
    return {"status": "saved", "key": key}

# ======== ADMINISTRACIÓN ========

ADMIN_API_KEY = os.getenv("Cv123Cv123", "Cv123Cv123")

def require_admin(x_api_key: Optional[str] = Header(default=None, alias="X-API-Key")):
    if not x_api_key or x_api_key != ADMIN_API_KEY:
        raise HTTPException(401, "API Key inválida")
    return True

@app.post("/reload", dependencies=[Depends(require_admin)])
def reload_all():
    global KB, SPECS, PERSONAL, LAYOUTS
    KB = load_knowledge(CSV_PATH)
    SPECS = load_specs(ESPEC_PATH)
    PERSONAL = load_personal()
    LAYOUTS = load_layouts()
    return {"status": "all_reloaded"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)