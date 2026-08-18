# BGH · Sistema Experto AC

Aplicación interna de Ingeniería formada por una API FastAPI y un frontend HTML/JavaScript sin framework. Consulta palletización y especificaciones desde CSV, y personal, layouts y tiempos desde JSON.

## Requisitos e instalación

- Python 3.11, 3.12 o 3.13. Python 3.14 todavía emite advertencias de
  compatibilidad desde la capa Pydantic V1 incluida por FastAPI y no forma parte
  de la matriz soportada de este proyecto.

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Para ejecutar las pruebas:

```bash
pip install -r requirements-dev.txt
pytest -q
```

## Configuración

La aplicación no contiene una clave administrativa predeterminada. Antes de usar cualquier operación de escritura, defina una clave solo en el entorno del proceso:

```bash
export ADMIN_API_KEY='una-clave-local-segura'
```

Si `ADMIN_API_KEY` no está definida, todas las operaciones administrativas permanecen bloqueadas con HTTP 503. Una clave incorrecta devuelve HTTP 401.

Los orígenes CORS permitidos se configuran como una lista separada por comas. El valor de desarrollo predeterminado permite servidores estáticos locales en el puerto 5500 y archivos abiertos directamente (`null`):

```bash
export ALLOWED_ORIGINS='http://127.0.0.1:5500,http://localhost:5500'
```

No incluya secretos reales en archivos versionados.

## Ejecución

Desde cualquier directorio puede ejecutar:

```bash
uvicorn main:app --reload --app-dir /ruta/al/repositorio
```

Desde la raíz del proyecto basta con:

```bash
uvicorn main:app --reload
```

Sirva `index.html` con un servidor estático cuyo origen esté incluido en `ALLOWED_ORIGINS`; por ejemplo:

```bash
python -m http.server 5500
```

Luego abra `http://127.0.0.1:5500` y mantenga `http://127.0.0.1:8000` como URL de API.

### Windows y solución de problemas de arranque

En Windows se recomienda seleccionar explícitamente una versión compatible:

```powershell
py -3.13 -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
python -m uvicorn main:app --reload
```

El archivo `modelos.json` debe estar junto a `main.py`. La carga de arranque usa
directamente `Path(__file__).resolve().parent / "modelos.json"`, por lo que no
depende del directorio actual ni de un alias global de ruta durante el
subproceso de `--reload`. Si un traceback todavía muestra literalmente
`load_models(MODELOS_PATH)`, se está ejecutando una copia anterior de `main.py`:
actualice todos los archivos de la misma revisión y elimine `__pycache__` antes
de reiniciar Uvicorn.

Para confirmar qué archivo está importando Python:

```powershell
Get-ChildItem -Recurse -Directory -Filter __pycache__ | Remove-Item -Recurse -Force
python -c "import main; print(main.__file__); print(len(main.MODELOS))"
python -m uvicorn main:app --reload
```

## Arquitectura actual

```text
index.html / styles.css   Frontend HTML, CSS y JavaScript
main.py                   API FastAPI y persistencia segura en archivos
palletizacion.csv         Catálogo y configuración de pallets
especificaciones.csv      Especificaciones por producto y línea
personal_linea.json       Dotación por modelo
layouts.json              Links y metadatos de layouts
tiempos_linea.json        Tiempos por puesto
modelos.json              Catálogo maestro de identidad de producto
```

Las rutas se resuelven respecto de `main.py`, no respecto del directorio desde el cual se inicia Uvicorn. Las escrituras JSON/CSV usan archivo temporal, `fsync`, reemplazo atómico y un único backup `.bak` para evitar acumulación ilimitada.

## Seguridad y autorización

Las consultas son públicas dentro del alcance de red configurado. Requieren `X-API-Key`:

- escritura de personal, layouts y tiempos;
- eliminación de layouts y tiempos;
- lectura o reemplazo administrativo de CSV;
- todas las recargas desde disco;
- verificación de acceso administrativo.

La interfaz conserva la clave únicamente en memoria hasta cerrar o recargar la página. Los CSV importados se validan completamente antes de reemplazar la versión activa. Las advertencias de coherencia industrial se registran, pero el sistema no altera automáticamente los datos.

## Datos industriales pendientes de validación

Los tres registros inverter de 24K declaran 9 unidades por pallet y, simultáneamente, 2 capas por 4 cajas. La aplicación registra una advertencia y conserva los valores originales para revisión de Ingeniería/Logística.

## Identidad de modelos

`modelos.json` es la fuente maestra de identidad. Cada producto del catálogo principal tiene un `model_id` único y estable, por ejemplo `mdl_000002`. El identificador no codifica capacidad, proveedor, modelo comercial ni línea, por lo que esos nombres pueden evolucionar sin obligar a reutilizar o recalcular el ID.

El catálogo conserva también `capacidad`, `proveedor` y `modelo` para resolver las relaciones actuales. Solo incorpora `sku_bgh` y `pnb` cuando existe una correspondencia directa en las fuentes actuales; los datos ambiguos permanecen como `null` y se informan en el reporte de integridad.

### Compatibilidad de API

Los endpoints existentes continúan aceptando la clave compuesta:

```text
capacidad + proveedor + modelo
```

Los endpoints orientados a identidad son:

- `GET /modelos`: catálogo maestro;
- `GET /modelos/{model_id}`: identidad de un modelo;
- `GET /modelos/{model_id}/resumen`: palletización, specs por línea, dotación, layout, tiempos y estados de completitud;
- `GET /modelos/integridad`: relaciones faltantes, huérfanas, ambiguas y advertencias conocidas.

Una misma identidad puede tener especificaciones para varias líneas. La línea es una dimensión relacionada y no genera otro `model_id`.

### Modelo activo en el frontend

Al elegir capacidad, proveedor y modelo en cualquier módulo, la interfaz resuelve su `model_id`, lo presenta en la barra superior y sincroniza los selects de Palletización, Ficha, Personal, Especificaciones, Layouts y Tiempos. Solo el `model_id` se conserva en `sessionStorage`; la clave administrativa continúa exclusivamente en memoria.

Al recargar la página, el frontend comprueba que el ID guardado siga presente en `/modelos`. Si existe, restaura el contexto; si ya no existe, elimina la selección guardada. La Ficha utiliza el resumen consolidado como dashboard mínimo sin reemplazar los demás módulos.

## Experiencia de consulta de Ingeniería

La pantalla **Inicio** concentra la selección por capacidad, proveedor y modelo,
un acceso rápido limitado al catálogo por SKU/PNB y los indicadores reales de
completitud. Al abrir un producto, **Resumen** presenta su identidad, métricas,
advertencias y disponibilidad de cada dominio.

La navegación contextual mantiene el Modelo Activo al abrir Especificaciones,
Palletización, Dotación, Layout o Tiempos y carga automáticamente la información
correspondiente. Los estados siempre incluyen texto e icono (`Disponible`,
`Faltante` o `Advertencia`) y no dependen únicamente del color.

La sección administrativa **Calidad de datos** consume `/modelos/integridad` y
expone cobertura, specs huérfanas, referencias SKU compartidas y modelos con
advertencias. No modifica ni completa automáticamente ninguna fuente industrial.

Los estilos se mantienen en `styles.css`; `index.html` conserva por ahora el
JavaScript para evitar una extracción masiva en esta etapa. Una separación a
`app.js` queda recomendada cuando se incorporen los próximos módulos.
