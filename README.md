# BGH · Sistema Experto AC

Proyecto FastAPI + frontend HTML para consultas de palletización, ficha técnica, personal de línea, layouts por modelo y tiempos por puesto.

## Ejecutar

```bash
pip install -r requirements.txt
uvicorn main:app --reload
```

Luego abrir `index.html` en el navegador y verificar que la API URL sea:

```text
http://127.0.0.1:8000
```

## Nueva mejora: Tiempos por puesto

La pestaña **Tiempos** permite:

- Seleccionar capacidad, proveedor y modelo.
- Cargar tiempos en segundos separados por coma.
- Definir límite de ciclo.
- Visualizar gráfico de barras con exceso en rojo.
- Guardar, cargar y eliminar tiempos por modelo.

Los datos se guardan en `tiempos_linea.json`.
