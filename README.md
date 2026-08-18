# BGH · Sistema Experto AC

Aplicación interna de Ingeniería formada por una API FastAPI y un frontend HTML/JavaScript sin framework. Consulta palletización y especificaciones desde CSV, y personal, layouts y tiempos desde JSON.

## Requisitos e instalación

- Python 3.11 o posterior.

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

## Arquitectura actual

```text
index.html / styles.css   Frontend HTML, CSS y JavaScript
main.py                   API FastAPI y persistencia segura en archivos
palletizacion.csv         Catálogo y configuración de pallets
especificaciones.csv      Especificaciones por producto y línea
personal_linea.json       Dotación por modelo
layouts.json              Links y metadatos de layouts
tiempos_linea.json        Tiempos por puesto
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
