# Etapa 6 — Auditoría técnica de la plantilla de IT

Fecha de auditoría: 2026-08-27  
Plantilla: `templates/it/BSIP_IT_template.xlsx`  
SHA-256 original: `42d32ba9bae598c5ec18a3f12c25ae1f18e54fba0d45450de0e713f322d61acf`

## Alcance y decisión

Esta auditoría se hizo directamente sobre el paquete OOXML, sin modificar la
plantilla. Todavía **no se selecciona una tecnología de exportación** ni se
implementa el generador: el ensayo de apertura y guardado con `openpyxl` no se
pudo ejecutar en el entorno porque la biblioteca no está instalada y tanto
PyPI como los repositorios APT están bloqueados por el proxy (HTTP 403).

La prueba queda como bloqueo técnico obligatorio. No es válido aprobar
`openpyxl` hasta comparar un archivo guardado sin cambios con este inventario,
en especial los 10 objetos DrawingML, el WMF, las 61 instancias de imagen, las
configuraciones de impresión y los archivos binarios de impresora.

## Inventario del paquete OOXML

El XLSX contiene 42 partes:

- libro, estilos, tema y cadenas compartidas;
- 2 worksheets y sus relaciones;
- 1 drawing y sus relaciones;
- 15 recursos de imagen: 13 JPEG, 1 PNG y 1 WMF;
- 2 configuraciones binarias de impresora (`printerSettings1.bin` y
  `printerSettings2.bin`);
- 3 elementos `customXml` con sus propiedades y relaciones;
- propiedades core, custom y app.

No hay partes EMF, VBA, controles ActiveX, comentarios, charts ni
`legacyDrawing`/VML. Sí hay shapes nativos de Office dentro de
`xl/drawings/drawing1.xml`, por lo que contar únicamente los archivos de imagen
no alcanza para validar preservación visual.

## Hojas, dimensiones, merges e impresión

### `Fijación cable de masa.`

- `sheetId=18`, dimensión declarada `A1:AG62`.
- 92 rangos combinados. Entre los estructurales principales están `A1:H1`,
  `I1:L1`, `M1:Y1`, `Z1:AF3`, `A6:A33`, `B6:B29`, `C7:Q29`, `R7:AF29`,
  `A36:B40` y `A43:AF43`.
- Área de impresión real: `$A$1:$AF$42` (nombre definido local
  `_xlnm.Print_Area`). Las filas 43–62 quedan fuera del área impresa aunque
  forman parte de la dimensión usada.
- Papel `9` (A4), horizontal, escala 94 %, centrado horizontal y vertical.
- Márgenes izquierdo, derecho, superior, inferior, encabezado y pie: 0.
- Conserva una relación a `printerSettings1.bin` y otra a `drawing1.xml`.

### `Revisiones`

- `sheetId=19`, dimensión declarada `A1:K17`.
- 41 rangos combinados, organizados en bloques de fecha, causa y responsable;
  por ejemplo `A1:K2`, `A3:B3`, `C3:I3`, `J3:K3` y sus equivalentes hasta la
  fila 17.
- No tiene un `_xlnm.Print_Area` definido.
- Orientación vertical; márgenes 0.7 izquierdo/derecho, 0.75
  superior/inferior y 0.3 encabezado/pie.
- Conserva una relación a `printerSettings2.bin`; no tiene drawing.

## Drawing, imágenes y objetos de Office

`drawing1.xml` contiene 71 anclas: 55 `oneCellAnchor` y 16
`twoCellAnchor`. Los objetos son:

- 61 `pic` (imágenes);
- 6 `sp` (shapes);
- 4 `cxnSp` (conectores/flechas);
- 0 charts, graphic frames o grupos.

Las 61 imágenes referencian los 15 recursos. `image6.jpeg` aparece en 47
instancias; cada uno de los otros 14 recursos aparece una vez. El recurso
vectorial `image7.wmf` está efectivamente referenciado y no es un archivo
huérfano.

Objetos Office que deben sobrevivir exactamente al round-trip:

| Nombre OOXML | Tipo / geometría | Ancla (índices base 0) |
| --- | --- | --- |
| `16 Conector recto de flecha` | `cxnSp` | col. 29, fila 19 → col. 29, fila 24 |
| `Elipse 71` | `sp`, elipse | col. 27, fila 24 → col. 28, fila 26 |
| `Rectángulo 86` | `sp`, rectángulo | col. 23, fila 17 → col. 24, fila 19 |
| `Rectangle 8` | `sp`, rectángulo con texto `a` | col. 28, fila 18 → col. 29, fila 19 |
| `36 Conector recto de flecha` | `cxnSp` | col. 28, fila 19 → col. 29, fila 24 |
| `Conector: angular 98` | `cxnSp` | col. 23, fila 19 → col. 25, fila 24 |
| `Elipse 82` | `sp`, elipse | col. 28, fila 24 → col. 29, fila 26 |
| `Flecha a la derecha con bandas 40` | `sp`, `stripedRightArrow` | col. 14, fila 20 → col. 15, fila 23 |
| `Rectángulo 91` | `sp`, rectángulo | col. 4, fila 7 → col. 5, fila 11 |
| `Conector: angular 92` | `cxnSp` | col. 5, fila 11 → col. 12, fila 22 |

Los offsets EMU, estilos, rotaciones, rellenos y terminaciones de flecha están
en el XML y también deben compararse; la tabla no propone coordenadas nuevas.

## Mapa real de campos existentes

El mapa siguiente registra únicamente celdas que ya contienen datos en la
plantilla. No constituye todavía un contrato de escritura.

### Encabezado de la instrucción

| Celda | Contenido actual / significado observado |
| --- | --- |
| `A1` | `INSTRUCCIÓN DE TRABAJO` |
| `I1` | Número de IT: `N° BSIP IT UOA4874` |
| `A2` | Etiqueta `ÁREA` |
| `C2` | Etiqueta `MODELO` |
| `I2` | Etiqueta `PROCESO` |
| `M2`, `O2`, `Q2` | Realizó, Lower O., Revisó |
| `U2` | Lista de distribución |
| `M3`, `O3`, `Q3`, `S3` | Etiquetas/valores de fecha |
| `A4` | Área actual: `A. A.` |
| `C4` | Descripción actual del modelo |
| `I4` | Etiqueta `CONTENIDO:` |
| `M4` | Contenido actual de la IT |
| `Z4`, `Z5`, `AA5`, `AB5` | Página X de Y |
| `AC4`, `AC5` | Revisión y valor actual |

### Operaciones, herramientas, materiales y EPP

| Celda/rango inicial | Contenido actual / significado observado |
| --- | --- |
| `A6`, `B6` | Descripción de operaciones / ayuda visual |
| `C6`, `R6` | Encabezados Paso 1 / Paso 2 |
| `C30`, `R30`, `R31` | Texto de instrucciones de los pasos |
| `C34` | Advertencia/criterio de aceptación |
| `A36` | Lista de herramientas |
| `C36`, `H36`, `O36` | Descripción, especificación y cantidad de herramienta |
| `C37`, `H37`, `O37` | Primera herramienta actual |
| `Q36` | Lista de materiales |
| `S36`, `T36`, `AA36`, `AE36` | N°, descripción, código y cantidad de material |
| `S37`, `T37`, `AA37`, `AE37`, `AA38` | Materiales actuales |
| `A41`, `E41`, `I41`, `M41`, `Q41`, `U41`, `Y41`, `AC41` | Tipos de EPP |
| `M42`, `Q42` | Selecciones EPP actuales (`x`) |

### Historial de revisiones

| Celda | Contenido actual / significado observado |
| --- | --- |
| `A1` | Título bilingüe del historial |
| `A3`, `C3`, `J3` | Fecha, causa y responsable |
| `A4`, `C4`, `J4` | Primera revisión registrada |

## Prueba de apertura/guardado sin cambios

### Estado

**No ejecutada por limitación del entorno; decisión tecnológica pendiente.**

Intentos realizados:

1. `python -c "import openpyxl"`: `ModuleNotFoundError`.
2. `python -m pip install openpyxl==3.1.5`: cinco intentos al índice PyPI,
   rechazados por el túnel con HTTP 403.
3. `apt-get update && apt-get install python3-openpyxl`: repositorios Ubuntu
   rechazados por el proxy con HTTP 403; no se instaló ningún paquete.
4. No hay LibreOffice/soffice instalado para efectuar una comprobación visual
   secundaria.

### Criterio de aceptación pendiente

En un entorno con `openpyxl` se debe guardar una **copia temporal**, nunca el
archivo original, y comparar como mínimo:

1. que se pueda abrir y guardar sin excepción ni warning de DrawingML;
2. lista de partes ZIP y relaciones antes/después;
3. 71 anclas, 61 `pic`, 6 `sp`, 4 `cxnSp` y sus nombres/geometrías;
4. los 15 binarios de imagen por hash, incluido `image7.wmf`;
5. las 2 configuraciones binarias de impresora;
6. las 3 partes `customXml` y relaciones;
7. hojas, 133 merges totales, área de impresión, orientación, escala, márgenes y
   centrado;
8. inspección visual en Excel de imágenes, shapes, conectores y flechas.

Si cualquiera de esos elementos desaparece o cambia, `openpyxl` queda
descartado para el exportador directo. Hasta completar esta prueba no se debe
comenzar frontend, SQLite ni generación de archivos.
