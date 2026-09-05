"""
Monitor BOE - Deteccion de expedientes de herencia abintestato
Fuente: API oficial de datos abiertos del BOE (https://boe.es/datosabiertos)
Uso: python monitor_boe_abintestato.py 2026-09-01 2026-09-05

Requisitos: pip install requests
"""

import sys
import csv
import time
import requests
from datetime import date, timedelta

BASE_URL = "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}"
HEADERS = {
    "Accept": "application/json",
    "User-Agent": "monitor-herencias/1.0 (contacto@tudominio.es)"
}

KEYWORDS = [
    "abintestato",
    "herencia yacente",
    "heredero abintestato",
    "declaracion de heredero",
    "sin herederos conocidos",
]

ORGANISMOS_OBJETIVO = [
    "hacienda",
    "economia y hacienda",
    "patrimonio del estado",
]


def daterange(start_date, end_date):
    d = start_date
    while d <= end_date:
        yield d
        d += timedelta(days=1)


def contiene_keyword(texto, keywords):
    texto_low = texto.lower()
    return any(k in texto_low for k in keywords)


def extraer_items(sumario_json):
    items = []

    def walk(node, contexto):
        if isinstance(node, dict):
            nuevo_contexto = dict(contexto)
            for campo in ("nombre", "titulo", "identificador", "control"):
                if campo in node and isinstance(node[campo], str):
                    nuevo_contexto[campo] = node[campo]

            if "identificador" in node or "control" in node:
                titulo = node.get("titulo", nuevo_contexto.get("titulo", ""))
                items.append({
                    "identificador": node.get("identificador", node.get("control", "")),
                    "titulo": titulo,
                    "departamento": nuevo_contexto.get("nombre", ""),
                    "urls": node.get("url_xml") or node.get("url_pdf") or node.get("url_html") or "",
                })

            for v in node.values():
                walk(v, nuevo_contexto)

        elif isinstance(node, list):
            for elem in node:
                walk(elem, contexto)

    walk(sumario_json, {})
    return items


def consultar_dia(fecha_str):
    url = BASE_URL.format(fecha=fecha_str)
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
    except requests.RequestException as e:
        print(f"[{fecha_str}] Error de conexion: {e}")
        return []

    if resp.status_code == 404:
        return []
    if resp.status_code != 200:
        print(f"[{fecha_str}] HTTP {resp.status_code}")
        return []

    try:
        data = resp.json()
    except ValueError:
        print(f"[{fecha_str}] Respuesta no es JSON valido")
        return []

    items = extraer_items(data)

    candidatos = []
    for it in items:
        texto_combinado = f"{it['titulo']} {it['departamento']}"
        if contiene_keyword(texto_combinado, KEYWORDS) or contiene_keyword(texto_combinado, ORGANISMOS_OBJETIVO):
            it["fecha"] = fecha_str
            candidatos.append(it)

    return candidatos


def main():
    if len(sys.argv) != 3:
        print("Uso: python monitor_boe_abintestato.py YYYY-MM-DD YYYY-MM-DD")
        sys.exit(1)

    fecha_inicio = date.fromisoformat(sys.argv[1])
    fecha_fin = date.fromisoformat(sys.argv[2])

    resultados = []
    for d in daterange(fecha_inicio, fecha_fin):
        fecha_str = d.strftime("%Y%m%d")
        print(f"Consultando {fecha_str}...")
        resultados.extend(consultar_dia(fecha_str))
        time.sleep(0.5)

    if not resultados:
        print("No se encontraron expedientes candidatos en el rango indicado.")
        return

    salida = "expedientes_abintestato.csv"
    with open(salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["fecha", "identificador", "departamento", "titulo", "urls"])
        writer.writeheader()
        for r in resultados:
            writer.writerow(r)

    print(f"\n{len(resultados)} expedientes candidatos guardados en {salida}")


if __name__ == "__main__":
    main()
