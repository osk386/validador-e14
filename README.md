# validador-e14

Herramienta de análisis automático de actas electorales colombianas **E-14** (Acta de Escrutinio de Jurados de Votación). Convierte PDFs de actas a JSON estructurado usando visión artificial (GPT-4.1) y detecta automáticamente inconsistencias matemáticas y posibles alteraciones en los documentos.

---

## ¿Qué hace?

Para cada acta E-14 en PDF el script:

1. **Convierte** cada página del PDF a imagen de alta resolución.
2. **Extrae** todos los datos del formulario (encabezado, nivelación de mesa, votos por candidato, totales) usando GPT-4.1 con visión.
3. **Valida** cinco reglas de consistencia (ver sección [Validaciones](#validaciones)).
4. **Genera** un JSON por acta y un reporte consolidado de inconsistencias.

---

## Requisitos previos

- Python **3.10** o superior
- Una **API key de OpenAI** con acceso al modelo `gpt-4.1-mini`

---

## Instalación

### 1. Clonar el repositorio

```bash
git clone <url-del-repo>
cd validador-e14
```

### 2. Crear el entorno virtual

```bash
python3 -m venv .venv
```

### 3. Activar el entorno virtual

**macOS / Linux:**
```bash
source .venv/bin/activate
```

**Windows (PowerShell):**
```powershell
.venv\Scripts\Activate.ps1
```

**Windows (cmd):**
```cmd
.venv\Scripts\activate.bat
```

### 4. Instalar dependencias

```bash
pip install -r requirements.txt
```

Las dependencias son:

| Paquete | Uso |
|---|---|
| `pymupdf` | Renderizar páginas del PDF a imagen |
| `openai` | Cliente oficial de la API de OpenAI |
| `httpx` | Transporte HTTP requerido por el cliente OpenAI |

---

## Configuración de la API key

El script necesita una API key de OpenAI. Hay dos formas de proveerla:

**Opción A — Variable de entorno (recomendada):**
```bash
export OPENAI_API_KEY="sk-..."
```

Para que persista entre sesiones, agrégala a tu `~/.zshrc` o `~/.bashrc`.

**Opción B — Argumento al ejecutar:**
```bash
python analizar.py --input ./MIS_ACTAS --api-key sk-...
```

---

## Uso

```bash
python analizar.py --input <carpeta_con_pdfs> [opciones]
```

### Argumentos

| Argumento | Requerido | Descripción | Por defecto |
|---|---|---|---|
| `--input` | ✅ | Carpeta que contiene los archivos `.pdf` a procesar | — |
| `--output` | ❌ | Carpeta donde se guardarán los JSONs y el reporte | `<input>/OUTPUT` |
| `--api-key` | ❌ | OpenAI API key (alternativa a la variable de entorno) | `$OPENAI_API_KEY` |
| `--dpi` | ❌ | Resolución para renderizar el PDF (más alto = mejor lectura, más lento) | `300` |
| `--pausa` | ❌ | Segundos de espera entre llamadas a la API (evita rate limits) | `1.5` |

### Ejemplos

Procesar la carpeta de prueba incluida:
```bash
python analizar.py --input ./TEST
```

Procesar una carpeta propia con opciones explícitas:
```bash
python analizar.py \
  --input ./MIS_ACTAS \
  --output ./RESULTADOS \
  --dpi 200 \
  --pausa 2
```

---

## Salidas generadas

Por cada ejecución se crean los siguientes archivos en la carpeta de salida:

### `<NOMBRE_ACTA>.json`

Un JSON por cada PDF procesado con la estructura completa del acta:

```json
{
  "encabezado": {
    "departamento_codigo": "16",
    "departamento_nombre": "BOGOTA D.C.",
    "municipio_codigo": "001",
    "municipio_nombre": "BOGOTA D.C.",
    "zona": "01",
    "puesto": "01",
    "mesa": "006",
    "lugar": "USAQUÉN"
  },
  "nivelacion_mesa": {
    "total_votantes_e11": 237,
    "total_votos_urna": 238,
    "total_votos_incinerados": 1
  },
  "candidatos": [
    {
      "numero": 1,
      "presidente": "IVÁN CEPEDA CASTRO",
      "vicepresidente": "AÍDA QUILCUÉ VIVAS",
      "agrupacion": "ACTO HISTÓRICO",
      "votos": 41
    }
  ],
  "otros_votos": {
    "votos_blanco": 6,
    "votos_nulos": 1,
    "votos_no_marcados": 1,
    "suma_total_declarada": 237
  },
  "validaciones": {
    "V1": { "resultado": "ok", "detalle": "..." },
    "V2": { "resultado": "ok", "detalle": "..." },
    "V3": { "resultado": "ok", "detalle": "..." },
    "V4": { "resultado": "ok", "detalle": "...", "campos_sospechosos": [] },
    "V5": { "resultado": "ok", "firmas_contadas": 5, "detalle": "..." }
  },
  "observaciones": ""
}
```

### `reporte_inconsistencias.txt`

Resumen consolidado de todos los archivos procesados, indicando cuáles pasaron todas las validaciones y cuáles presentaron problemas, con el detalle de cada falla.

---

## Validaciones

El script aplica cinco validaciones a cada acta:

| Código | Nombre | Regla |
|---|---|---|
| **V1** | Nivelación de mesa | `abs(votos_urna − votantes_e11) == votos_incinerados` |
| **V2** | Aritmética interna | `suma(votos_candidatos) + blanco + nulos + no_marcados == suma_total_declarada` |
| **V3** | Coherencia con urna | `suma_total_declarada == min(votos_urna, votantes_e11)` |
| **V4** | Integridad visual | Ningún dígito manuscrito presenta señales físicas de alteración (trazo doble, corrector, cambio de tinta, etc.) |
| **V5** | Firmas de jurados | El formulario tiene al menos 3 firmas manuscritas visibles |

Cada validación puede arrojar uno de estos resultados:
- `ok` — sin problemas
- `inconsistencia` — la regla no se cumple
- `sospechoso` — (solo V4) se detectaron señales de posible alteración
- `no_verificable` — algún valor necesario es ilegible o nulo

---

## Estructura del proyecto

```
validador-e14/
├── analizar.py              # Script principal
├── README.md
├── requirements.txt         # Dependencias
├── .gitignore
└── TEST/                    # Datos de prueba
    ├── MESA_6.pdf
    ├── MESA_27.pdf
    ├── MESA_33.pdf
    ├── MESA_34.pdf
    └── OUTPUT/              # Resultados del último test
        ├── MESA_6.json
        ├── MESA_27.json
        ├── MESA_33.json
        ├── MESA_34.json
        └── reporte_inconsistencias.txt
```

---

## Notas técnicas

- El modelo usado es `gpt-4.1-mini` con `temperature=0` para máxima consistencia en la transcripción.
- Los PDFs se renderizan a 300 DPI por defecto para garantizar legibilidad de los dígitos manuscritos. Se puede bajar a 150–200 DPI para acelerar el procesamiento si la calidad de los PDFs es alta.
- Si el modelo devuelve un bloque markdown en lugar de JSON puro, el script lo limpia automáticamente.
- En caso de error de parseo, el JSON de salida incluye los campos `_error_parseo` y `_respuesta_cruda` para diagnóstico.


## Correr los tests de ejemplo

La carpeta `TEST/` incluye 4 actas de prueba reales. Para ejecutarlas:

```bash
# Asegúrate de tener el entorno virtual activo y la API key configurada
source .venv/bin/activate
export OPENAI_API_KEY="sk-..."

python analizar.py --input ./TEST
```

Los resultados se guardarán en `TEST/OUTPUT/`. Puedes compararlos con los JSONs y el reporte que ya están en esa carpeta para verificar que el script produce resultados consistentes.

Para regenerarlos desde cero (sobreescribiendo los existentes):

```bash
python analizar.py --input ./TEST --output ./TEST/OUTPUT
```

Al terminar verás en consola un resumen como este:

```
═══════════════════════════════════════════════════════
  Procesando 4 acta(s) E-14
  Input : TEST
  Output: TEST/OUTPUT
═══════════════════════════════════════════════════════

[1/4] MESA_27.pdf ... ✓ guardado
[2/4] MESA_33.pdf ... ✓ guardado
[3/4] MESA_34.pdf ... ✓ guardado
[4/4] MESA_6.pdf  ... ✓ guardado

───────────────────────────────────────────────────────
  Procesamiento completado.
  JSONs guardados en : TEST/OUTPUT
  Reporte generado   : reporte_inconsistencias.txt

  ⚠  1 archivo(s) con inconsistencias:
     • MESA_33.pdf
───────────────────────────────────────────────────────
```

---

## Ejemplo de archivo de reporte de inconsistencias

REPORTE DE INCONSISTENCIAS — ACTAS E-14
Generado: 2026-06-23 01:18:11

Total archivos procesados : 4
Con inconsistencias        : 1
Sin inconsistencias        : 3

────────────────────────────────────────────────────────────
DETALLE POR ARCHIVO
────────────────────────────────────────────────────────────

[✓ OK] MESA_27.pdf

[✗ PROBLEMA] MESA_33.pdf
        • V2: inconsistencia — La suma de votos candidatos (110) más votos en blanco (4), nulos (1) y no marcados (0) es 115, diferente a la suma total declarada (155).
        • V3: inconsistencia — La suma total declarada (155) no es igual al menor valor entre total votos urna (155) y total votantes E-11 (155), que es 155, pero la suma total calculada es 115.

[✓ OK] MESA_34.pdf

[✓ OK] MESA_6.pdf

────────────────────────────────────────────────────────────
SOLO ARCHIVOS CON PROBLEMAS
────────────────────────────────────────────────────────────
  • MESA_33.pdf
      V2: inconsistencia — La suma de votos candidatos (110) más votos en blanco (4), nulos (1) y no marcados (0) es 115, diferente a la suma total declarada (155).
      V3: inconsistencia — La suma total declarada (155) no es igual al menor valor entre total votos urna (155) y total votantes E-11 (155), que es 155, pero la suma total calculada es 115.
