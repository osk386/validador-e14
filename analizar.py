"""
procesar_e14.py
---------------
Procesa actas E-14 en PDF usando GPT-4.1 con visión.
Genera un JSON por acta y un reporte final de inconsistencias.

Uso:
    python procesar_e14.py --input ./INPUT --output ./OUTPUT --api-key sk-...

    O bien define la variable de entorno OPENAI_API_KEY y omite --api-key.
"""

import argparse
import base64
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import fitz  # PyMuPDF  →  pip install pymupdf
from openai import OpenAI

# ──────────────────────────────────────────────
# PROMPT + SCHEMA (embebidos directamente)
# ──────────────────────────────────────────────
SYSTEM_PROMPT = """Eres un asistente especializado en procesar actas electorales colombianas E-14 (Acta de Escrutinio de Jurados de Votación).

Se te proporcionará la imagen de un formulario E-14 (puede ser de una o varias páginas). Tu tarea es:

1. Extraer con precisión todos los valores numéricos y de identificación del formulario.
2. Transcribir los datos al JSON exacto definido más abajo.
3. Validar las consistencias matemáticas indicadas y reportar cualquier inconsistencia.
4. Detectar posibles alteraciones en los caracteres escritos a mano y reportarlas.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
INSTRUCCIONES DE LECTURA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Los valores numéricos en el formulario aparecen acompañados de puntos (●) que son marcas de posición preimpresas — NO son parte del número. Lee solo los dígitos escritos a mano o impresos junto a esos puntos.

Ejemplo: ● 4 7 → valor = 47 | ● ● 0 → valor = 0 | ● ● 1 → valor = 1

Si un valor es ilegible o ambiguo, usa null y descríbelo en el campo "observaciones".

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
DETECCIÓN DE ALTERACIONES
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Analiza visualmente cada dígito manuscrito buscando evidencia CLARA Y CONCRETA de manipulación.

REGLA CRÍTICA — UMBRAL ALTO: Solo marca un campo como sospechoso si observas al menos UNA de las siguientes señales físicas inconfundibles. La escritura irregular, inclinada o poco prolija por sí sola NO es suficiente — todos los humanos escriben diferente.

Señales que SÍ justifican marcar como sospechoso:
- TRAZOS DOBLES VISIBLES: se ven claramente dos capas de escritura superpuestas en el mismo dígito.
- ZONA RASPADA O CON CORRECTOR: el papel muestra raspado, mancha blanca de corrector, o una textura diferente bajo el dígito.
- CAMBIO DE TINTA EVIDENTE: el dígito tiene un color de tinta marcadamente diferente al resto de los dígitos de la misma fila (ej. azul oscuro vs negro, trazo más grueso o más fino de forma aislada).
- DÍGITO QUE FÍSICAMENTE NO CABE: el número está claramente escrito encima del borde de la celda o aplasta a otro dígito, sugiriendo que fue añadido después.

Señales que NO son suficientes por sí solas para marcar como sospechoso:
- Escritura poco clara o difícil de leer.
- Trazo con diferente presión sin cambio de color.
- Dígito con forma atípica pero coherente con el estilo general del escribiente.
- Ambigüedad de lectura (ej. 1 vs 7): transcribe el valor más probable y anota la ambigüedad solo en "observaciones".

Si no hay ninguna señal física inconfundible → resultado V4 = "ok", detalle = "caracteres consistentes y legibles", campos_sospechosos = [].

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECCIÓN 1 — ENCABEZADO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Extrae del recuadro superior:
- DEPARTAMENTO (código y nombre, ej: "16 - BOGOTA D.C.")
- MUNICIPIO (código y nombre)
- ZONA, PUESTO, MESA (números)
- LUGAR (nombre del lugar)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECCIÓN 2 — NIVELACIÓN DE LA MESA
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Extrae los tres valores de la tabla "NIVELACIÓN DE LA MESA":
- TOTAL VOTANTES FORMULARIO E-11
- TOTAL VOTOS EN LA URNA
- TOTAL VOTOS INCINERADOS

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECCIÓN 3 — VOTACIÓN POR CANDIDATO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Para cada fila de candidato (identificada por número 1, 2, 3...):
- Número del candidato
- Nombre(s) del candidato (presidente / vicepresidente)
- Agrupación política
- Votos obtenidos

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
SECCIÓN 4 — OTROS VOTOS Y SUMA TOTAL
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Extrae:
- VOTOS EN BLANCO
- VOTOS NULOS
- VOTOS NO MARCADOS
- SUMA TOTAL (candidatos + en blanco + nulos + no marcados)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
VALIDACIONES REQUERIDAS
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

V1 — Nivelación de mesa: |Urna - E-11| = Incinerados:
  abs(total_votos_urna - total_votantes_e11) == total_votos_incinerados

  Concepto: la nivelación de mesa iguala los votos con los votantes registrados.
  La diferencia ABSOLUTA entre urna y E-11 siempre debe coincidir con los incinerados:
  - Si urna > e11: había votos de más → se incineró el exceso. incinerados = urna - e11
  - Si e11 > urna: había votantes de más → se incineró la diferencia. incinerados = e11 - urna
  - Si urna == e11: no hubo incineración. incinerados = 0

  IMPORTANTE: si incinerados = 0, simplemente verifica que urna == e11.
  Nunca reportes inconsistencia por la dirección de la diferencia, solo por si el valor absoluto no cuadra.

V2 — Aritmética interna cierra:
  sum(votos candidatos) + votos_blanco + votos_nulos + votos_no_marcados == suma_total_declarada

V3 — Suma total = votos efectivamente contabilizados:
  suma_total_declarada == min(total_votos_urna, total_votantes_e11)

  Concepto: los votos incinerados NO se contabilizan, por lo que la suma total
  de candidatos + blanco + nulos + no marcados debe igualar al menor valor entre
  urna y E-11 (el que quedó después de la nivelación).
  Ejemplo: urna=215, e11=214, incinerados=1 → suma_total debe ser 214, no 215.

V4 — Integridad visual de caracteres:
  Ningún dígito manuscrito presenta señales físicas inconfundibles de alteración (ver sección DETECCIÓN DE ALTERACIONES).

V5 — Firmas de jurados:
  El formulario debe tener al menos 3 casillas de firma con firma manuscrita visible.
  Contar solo casillas con trazo manuscrito real; NO contar casillas vacías ni con solo número de cédula.

Para V1, V2, V3: resultado puede ser "ok", "inconsistencia" o "no_verificable" (si algún valor es null).
RECORDATORIO V1: la fórmula correcta es abs(total_votos_urna - total_votantes_e11) == total_votos_incinerados. La diferencia absoluta entre urna y E-11 debe ser exactamente igual a los incinerados, sin importar cuál sea mayor.
Para V4: resultado puede ser "ok", "sospechoso" o "no_verificable". En detalle, describe hallazgos por campo; si todo está bien escribe "caracteres consistentes y legibles".
Para V5: resultado puede ser "ok" (>=3 firmas), "inconsistencia" (<3 firmas) o "no_verificable" (sección no visible). En detalle indica el número exacto contado.

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
FORMATO DE SALIDA — JSON ESTRICTO
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

Responde ÚNICAMENTE con el siguiente JSON válido. No agregues texto antes ni después.
No incluyas bloques de código markdown (sin ```json). Solo el objeto JSON puro.

{
  "encabezado": {
    "departamento_codigo": "<string o null>",
    "departamento_nombre": "<string o null>",
    "municipio_codigo": "<string o null>",
    "municipio_nombre": "<string o null>",
    "zona": "<string o null>",
    "puesto": "<string o null>",
    "mesa": "<string o null>",
    "lugar": "<string o null>"
  },
  "nivelacion_mesa": {
    "total_votantes_e11": <integer o null>,
    "total_votos_urna": <integer o null>,
    "total_votos_incinerados": <integer o null>
  },
  "candidatos": [
    {
      "numero": <integer>,
      "presidente": "<string o null>",
      "vicepresidente": "<string o null>",
      "agrupacion": "<string o null>",
      "votos": <integer o null>
    }
  ],
  "otros_votos": {
    "votos_blanco": <integer o null>,
    "votos_nulos": <integer o null>,
    "votos_no_marcados": <integer o null>,
    "suma_total_declarada": <integer o null>
  },
  "calculos": {
    "suma_votos_candidatos": <integer o null>,
    "suma_total_calculada": <integer o null>
  },
  "validaciones": {
    "V1": {
      "resultado": "ok|inconsistencia|no_verificable",
      "detalle": "<descripción>"
    },
    "V2": {
      "resultado": "ok|inconsistencia|no_verificable",
      "detalle": "<descripción>"
    },
    "V3": {
      "resultado": "ok|inconsistencia|no_verificable",
      "detalle": "<descripción>"
    },
    "V4": {
      "resultado": "ok|sospechoso|no_verificable",
      "detalle": "<descripción>",
      "campos_sospechosos": [
        {
          "campo": "<nombre del campo>",
          "hallazgo": "<descripción física concreta>",
          "valor_leido": <integer, string o null>
        }
      ]
    },
    "V5": {
      "resultado": "ok|inconsistencia|no_verificable",
      "firmas_contadas": <integer o null>,
      "detalle": "<descripción>"
    }
  },
  "observaciones": "<string, vacío si no hay>"
}
"""


# ──────────────────────────────────────────────
# UTILIDADES
# ──────────────────────────────────────────────

def pdf_a_imagenes_b64(pdf_path: Path, dpi: int = 200) -> list[str]:
    """Convierte cada página del PDF a PNG en base64 (DPI=200 para buena legibilidad)."""
    doc = fitz.open(str(pdf_path))
    imagenes = []
    mat = fitz.Matrix(dpi / 72, dpi / 72)
    for pagina in doc:
        pix = pagina.get_pixmap(matrix=mat, colorspace=fitz.csRGB)
        datos_png = pix.tobytes("png")
        imagenes.append(base64.b64encode(datos_png).decode("utf-8"))
    doc.close()
    return imagenes


def llamar_gpt4(client: OpenAI, imagenes_b64: list[str], nombre_archivo: str) -> dict:
    """Envía las imágenes del acta a GPT-4.1 y retorna el JSON parseado."""
    # Construir el mensaje: texto + imágenes
    contenido = [{"type": "text", "text": SYSTEM_PROMPT}]
    for i, img_b64 in enumerate(imagenes_b64):
        contenido.append({
            "type": "image_url",
            "image_url": {
                "url": f"data:image/png;base64,{img_b64}",
                "detail": "high"   # máxima resolución de análisis
            }
        })

    respuesta = client.chat.completions.create(
        model="gpt-4.1-mini",
        messages=[{"role": "user", "content": contenido}],
        max_tokens=4096,
        temperature=0,   # determinista para transcripción
    )

    texto = respuesta.choices[0].message.content.strip()

    # Limpiar posibles bloques markdown que el modelo agregue
    if texto.startswith("```"):
        lineas = texto.splitlines()
        texto = "\n".join(
            l for l in lineas
            if not l.strip().startswith("```")
        )

    try:
        return json.loads(texto)
    except json.JSONDecodeError as e:
        # Si falla el parseo, devolver un objeto de error pero conservar el texto crudo
        return {
            "_error_parseo": str(e),
            "_respuesta_cruda": texto
        }


def hay_inconsistencias(resultado: dict) -> list[str]:
    """Retorna lista de validaciones fallidas (no-ok). Vacía si todo está bien."""
    problemas = []
    validaciones = resultado.get("validaciones", {})
    estados_fallo = {"inconsistencia", "sospechoso", "no_verificable"}
    for vid, datos in validaciones.items():
        if isinstance(datos, dict):
            r = datos.get("resultado", "")
            if r in estados_fallo:
                detalle = datos.get("detalle", "")
                problemas.append(f"{vid}: {r} — {detalle}")
    if "_error_parseo" in resultado:
        problemas.append(f"ERROR_PARSEO: {resultado['_error_parseo']}")
    return problemas


def generar_reporte(resumen: list[dict], output_dir: Path) -> Path:
    """Genera reporte_inconsistencias.txt con los archivos problemáticos."""
    ruta = output_dir / "reporte_inconsistencias.txt"
    ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    lineas = [
        "=" * 60,
        f"REPORTE DE INCONSISTENCIAS — ACTAS E-14",
        f"Generado: {ts}",
        "=" * 60,
        "",
        f"Total archivos procesados : {len(resumen)}",
        f"Con inconsistencias        : {sum(1 for r in resumen if r['problemas'])}",
        f"Sin inconsistencias        : {sum(1 for r in resumen if not r['problemas'])}",
        "",
        "─" * 60,
        "DETALLE POR ARCHIVO",
        "─" * 60,
    ]

    for item in resumen:
        estado = "✗ PROBLEMA" if item["problemas"] else "✓ OK"
        lineas.append(f"\n[{estado}] {item['archivo']}")
        if item["problemas"]:
            for p in item["problemas"]:
                lineas.append(f"        • {p}")
        if item.get("error_api"):
            lineas.append(f"        • ERROR API: {item['error_api']}")

    lineas += [
        "",
        "─" * 60,
        "SOLO ARCHIVOS CON PROBLEMAS",
        "─" * 60,
    ]
    con_problemas = [r for r in resumen if r["problemas"] or r.get("error_api")]
    if con_problemas:
        for item in con_problemas:
            lineas.append(f"  • {item['archivo']}")
            for p in item["problemas"]:
                lineas.append(f"      {p}")
    else:
        lineas.append("  (ninguno)")

    ruta.write_text("\n".join(lineas), encoding="utf-8")
    return ruta


# ──────────────────────────────────────────────
# MAIN
# ──────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Procesa actas E-14 en PDF con GPT-4.1")
    parser.add_argument("--input",   required=True, help="Carpeta con los PDFs de entrada")
    parser.add_argument("--output",  default=None,  help="Carpeta de salida (default: INPUT/OUTPUT)")
    parser.add_argument("--api-key", default=None,  help="OpenAI API key (o usa OPENAI_API_KEY)")
    parser.add_argument("--dpi",     type=int, default=300, help="DPI para renderizar el PDF (default: 300)")
    parser.add_argument("--pausa",   type=float, default=1.5, help="Segundos de pausa entre llamadas API (default: 1.5)")
    args = parser.parse_args()

    # ── Validar carpetas
    input_dir = Path(args.input)
    output_dir = Path(args.output) if args.output else input_dir / "OUTPUT"
    if not input_dir.exists():
        print(f"ERROR: La carpeta de entrada no existe: {input_dir}")
        sys.exit(1)
    output_dir.mkdir(parents=True, exist_ok=True)

    # ── Cliente OpenAI
    api_key = args.api_key or os.environ.get("OPENAI_API_KEY")
    if not api_key:
        print("ERROR: Falta la API key. Usa --api-key o define OPENAI_API_KEY.")
        sys.exit(1)
    client = OpenAI(api_key=api_key)

    # ── Listar PDFs
    pdfs = sorted(input_dir.glob("*.pdf"))
    if not pdfs:
        print(f"No se encontraron archivos .pdf en: {input_dir}")
        sys.exit(0)

    print(f"\n{'═'*55}")
    print(f"  Procesando {len(pdfs)} acta(s) E-14")
    print(f"  Input : {input_dir}")
    print(f"  Output: {output_dir}")
    print(f"{'═'*55}\n")

    resumen = []

    for i, pdf_path in enumerate(pdfs, 1):
        nombre = pdf_path.name
        salida = output_dir / (pdf_path.stem + ".json")
        print(f"[{i}/{len(pdfs)}] {nombre} ...", end=" ", flush=True)

        error_api = None
        resultado = {}

        try:
            imagenes = pdf_a_imagenes_b64(pdf_path, dpi=args.dpi)
            resultado = llamar_gpt4(client, imagenes, nombre)
            # Agregar metadato del archivo fuente
            resultado["_archivo_fuente"] = nombre
            resultado["_procesado_en"] = datetime.now().isoformat()

            salida.write_text(
                json.dumps(resultado, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print("✓ guardado")

        except Exception as e:
            error_api = str(e)
            resultado["_archivo_fuente"] = nombre
            resultado["_error_api"] = error_api
            salida.write_text(
                json.dumps(resultado, ensure_ascii=False, indent=2),
                encoding="utf-8"
            )
            print(f"✗ ERROR: {error_api}")

        problemas = hay_inconsistencias(resultado)
        resumen.append({
            "archivo":   nombre,
            "problemas": problemas,
            "error_api": error_api,
        })

        # Pausa entre llamadas para respetar rate limits
        if i < len(pdfs):
            time.sleep(args.pausa)

    # ── Reporte final
    ruta_reporte = generar_reporte(resumen, output_dir)
    print(f"\n{'─'*55}")
    print(f"  Procesamiento completado.")
    print(f"  JSONs guardados en : {output_dir}")
    print(f"  Reporte generado   : {ruta_reporte.name}")

    con_problemas = [r for r in resumen if r["problemas"] or r["error_api"]]
    if con_problemas:
        print(f"\n  ⚠  {len(con_problemas)} archivo(s) con inconsistencias:")
        for item in con_problemas:
            print(f"     • {item['archivo']}")
    else:
        print("\n  ✓ Todas las actas pasaron las validaciones.")

    print(f"{'─'*55}\n")


if __name__ == "__main__":
    main()
