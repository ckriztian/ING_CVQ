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

### Fuentes de verdad y sincronización administrativa

| Campo | Fuente autoritativa |
| --- | --- |
| `model_id` | `modelos.json` (estable y no reutilizable) |
| `capacidad`, `proveedor`, `modelo` | `modelos.json` para identidad; deben coincidir con `palletizacion.csv` |
| `sku_bgh` | columna `sku` de `palletizacion.csv`, sincronizada al guardar desde Administración |
| `pnb` | `modelos.json`; no se sobrescribe desde palletización |

`POST /admin/csv/replace` valida primero el CSV, conserva los `model_id`,
sincroniza únicamente `sku_bgh`, persiste ambas fuentes mediante las escrituras
atómicas existentes y recarga los índices en memoria. Una alta, baja o
modificación de `capacidad/proveedor/modelo` se rechaza para que no sea
interpretada arbitrariamente como un renombrado o un producto nuevo.

### Modelo activo en el frontend

Al elegir capacidad, proveedor y modelo en cualquier módulo, la interfaz resuelve su `model_id`, lo presenta en la barra superior y sincroniza los selects de Palletización, Ficha, Personal, Especificaciones, Layouts y Tiempos. Solo el `model_id` se conserva en `sessionStorage`; la clave administrativa continúa exclusivamente en memoria.

Al recargar la página, el frontend comprueba que el ID guardado siga presente en `/modelos`. Si existe, restaura el contexto; si ya no existe, elimina la selección guardada. La Ficha utiliza el resumen consolidado como dashboard mínimo sin reemplazar los demás módulos.

## Memoria de Ingeniería

Los cambios, notas y recordatorios por modelo se guardan exclusivamente en
`engineering_history.db`, una base SQLite dedicada. El vínculo lógico con el
catálogo se realiza mediante el `model_id`; antes de crear un cambio, la API
comprueba que esa identidad exista en `modelos.json`.

La base se inicializa de forma idempotente en el primer acceso y usa una
conexión por operación, `busy_timeout` y modo WAL. No contiene credenciales ni
datos ficticios. Las lecturas son públicas dentro del alcance actual de la
aplicación; crear y editar cambios requiere `X-API-Key`.

Estados disponibles:

- `evaluation`: En evaluación;
- `active`: Vigente;
- `superseded`: Reemplazado;
- `closed`: Cerrado.

Un recordatorio se muestra proactivamente únicamente cuando el cambio está
`active` y `remind_next_production` es verdadero. Cerrar o reemplazar un cambio
lo conserva en el historial, pero deja de mostrarlo como recordatorio vigente.

Endpoints:

- `GET /cambios/configuracion`;
- `GET /modelos/{model_id}/cambios` con filtros `status`, `change_type` y `remind_next_production`;
- `GET /cambios/{change_id}`;
- `POST /modelos/{model_id}/cambios` (administración);
- `PATCH /cambios/{change_id}` (administración).

### Respaldo del historial

`engineering_history.db` y sus archivos WAL están excluidos de Git porque
pueden contener conocimiento productivo real. La base debe incorporarse al
esquema corporativo de backups junto con `engineering_history.db-wal` cuando
este exista. Para una copia consistente con la aplicación en uso se recomienda
utilizar el mecanismo de backup de SQLite o detener brevemente la aplicación;
no reemplazar ni sobrescribir la base desde la administración de CSV.

### Validación manual del flujo

1. Seleccionar un Modelo Activo y autenticarse.
2. Abrir **Cambios de Ingeniería** y registrar un cambio vigente con recordatorio.
3. Confirmar el historial, la alerta de Home y la sección del Dashboard.
4. Cambiar de modelo y comprobar que el recordatorio desaparece.
5. Volver al modelo original, recargar el navegador y reiniciar Uvicorn para
   confirmar que el cambio reaparece y permanece persistido.

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

## Comparador de modelos

La herramienta **Comparar modelos** es pública y consulta dos veces
`GET /modelos/{model_id}/resumen`; no agrega un endpoint de comparación ni
requiere credenciales. El Modelo Activo se propone como Modelo A y los deltas
numéricos se calculan siempre como `B − A`.

La comparación cubre identidad, comparabilidad por dominio, palletización,
especificaciones separadas por línea, dotación por sector, tiempos por puesto y
metadatos de layout. Los sectores se alinean únicamente normalizando espacios,
mayúsculas y diacríticos; nombres semánticamente distintos no se fusionan. Los
datos ausentes se presentan como `Sin dato`, nunca como cero.

## Consulta y edición de dotación

Dotación abre siempre en modo de solo lectura con métricas, tabla, participación
y total. El editor solo aparece cuando existe una API key administrativa
validada en memoria. Guardar continúa usando el `POST /personal` protegido,
recarga la fuente y vuelve a consulta; cancelar o navegar con cambios pendientes
solicita confirmación. Un administrador puede iniciar una dotación vacía, pero
el sistema no inventa sectores.

## Gestor de Instrucciones de Trabajo

El módulo **Instrucciones de Trabajo** separa el identificador interno
`IT-000001` del código documental corporativo y persiste el contenido en
`work_instructions.db`, sin utilizar la base de Memoria de Ingeniería. Las
lecturas son públicas dentro de la aplicación y todas las escrituras reutilizan
la autenticación `X-API-Key`.

Cada revisión conserva procedimientos ordenados, materiales, herramientas, EPP
e imágenes opcionales guardadas bajo `data/work_instructions/`. Publicar una
revisión es transaccional: la revisión activa anterior pasa a `obsolete` y la
nueva `draft` pasa a `active`. El editor ofrece acciones rápidas, plantillas de
frase, duplicación y reordenamiento, y una vista previa HTML.

`work_instruction_exporter.py` implementa un adaptador desacoplado basado en
Microsoft Excel COM. En Windows se instalan las dependencias opcionales con
`pip install -r requirements-windows.txt`; Linux continúa usando solamente
`requirements.txt` y responde HTTP 503 de manera controlada.

El adaptador abre siempre una instancia aislada mediante `DispatchEx`, trabaja
sobre una copia temporal de `templates/it/BSIP_IT_template.xlsx`, elimina por
nombre los objetos específicos de los procedimientos del ejemplo y conserva
los recursos corporativos. Para diagnosticar y probar la integración en una PC
con Microsoft Excel instalado:

```bash
python scripts/check_excel_com.py
python scripts/test_it_excel_export.py
```

El segundo comando genera un archivo bajo `exports_test/` sin acceder a
`work_instructions.db`. Superar estos scripts no sustituye la inspección visual
manual del libro generado en Microsoft Excel.
