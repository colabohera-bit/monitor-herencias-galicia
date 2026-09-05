"""
Pipeline integrado v2 - Deteccion y analisis de expedientes de herencia abintestato
Fuentes: DOG (Xunta de Galicia), Tablon notarial de Vigo, Sede de la Diputacion de Pontevedra, BOE

Novedades v2:
- Parser de detalle DOG: extrae DNI, fechas, municipios, num. expediente y calcula plazo limite
- Marcador de "candidato a premio": detecta expedientes sin bienes explicitos en el texto
  (inmuebles/cuentas quedan EXCLUIDOS de premio en Galicia; otros bienes SI son premio-elegibles)

Requisitos: pip install requests beautifulsoup4 lxml python-dateutil

Uso:
    python pipeline_herencias_galicia.py
Salida:
    expedientes_galicia.csv
"""

import csv
import re
import time
import requests
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "monitor-herencias-galicia/1.0 (contacto@tudominio.es)",
    "Accept": "text/html,application/json",
}

KEYWORDS_ABIERTO = ["incoado", "incoacion", "incoar", "provisional", "certificado provisional", "expuesto"]
KEYWORDS_CERRADO = ["definitivo", "declara heredera", "adjudicacion", "resolucion final", "unica y universal heredera"]
KEYWORDS_INTERES = ["abintestato", "herencia yacente", "heredero", "heredera", "declaracion de heredero"]
KEYWORDS_BIEN_EXCLUIDO = ["inmueble", "vivienda", "piso", "parcela", "finca", "cuenta", "deposito", "saldo bancario"]

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}


def normaliza(texto):
    return (texto or "").lower().strip()


def clasifica_estado(texto_combinado):
    t = normaliza(texto_combinado)
    if any(k in t for k in KEYWORDS_ABIERTO):
        return "ABIERTO / ventana de oportunidad"
    if any(k in t for k in KEYWORDS_CERRADO):
        return "CERRADO / revisar via nulidad"
    return "SIN CLASIFICAR / revisar manualmente"


def marca_candidato_premio(texto_completo):
    t = normaliza(texto_completo)
    menciona_bien_excluido = any(k in t for k in KEYWORDS_BIEN_EXCLUIDO)
    return not menciona_bien_excluido


def parsea_fecha_larga(texto):
    m = re.search(r"(\d{1,2})\s+de\s+([a-zA-Z]+)\s+de\s+(\d{4})", texto)
    if not m:
        return None
    dia, mes_txt, anio = m.groups()
    mes = MESES.get(normaliza(mes_txt))
    if not mes:
        return None
    try:
        return date(int(anio), mes, int(dia))
    except ValueError:
        return None


def parsea_detalle_dog(url, texto_html=None):
    if texto_html is None:
        try:
            resp = requests.get(url, headers=HEADERS, timeout=20)
            if resp.status_code != 200:
                return None
            soup = BeautifulSoup(resp.text, "lxml")
            texto_html = soup.get_text(" ", strip=True)
        except requests.RequestException:
            return None

    causante = ""
    m_nombre = re.search(r"^([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]+?),\s+con\s+DNI", texto_html)
    if m_nombre:
        causante = m_nombre.group(1).strip()

    dni = ""
    m_dni = re.search(r"DNI\s+([\dA-Z\-]+)", texto_html)
    if m_dni:
        dni = m_dni.group(1)

    m_expediente = re.search(r"expediente\s+([A-Z]{2,4}/\d{4}/\d+)", texto_html, re.IGNORECASE)
    expediente = m_expediente.group(1) if m_expediente else ""

    m_ayuntamientos = re.search(r"ayuntamientos de ([^,]+(?:,[^,]+){0,3}),?\s+as[ií] como", texto_html)
    municipios = m_ayuntamientos.group(1).strip() if m_ayuntamientos else ""

    fecha_resolucion = None
    m_fecha_res = re.search(r"Compostela,\s+(\d{1,2}\s+de\s+[a-zA-Z]+\s+de\s+\d{4})", texto_html)
    if m_fecha_res:
        fecha_resolucion = parsea_fecha_larga(m_fecha_res.group(1))

    plazo_limite = None
    if fecha_resolucion:
        plazo_limite = fecha_resolucion + relativedelta(years=1)

    candidato_premio = marca_candidato_premio(texto_html)

    return {
        "causante": causante,
        "dni": dni,
        "expediente": expediente,
        "municipios": municipios,
        "fecha_resolucion": fecha_resolucion.isoformat() if fecha_resolucion else "",
        "plazo_limite_estimado": plazo_limite.isoformat() if plazo_limite else "",
        "candidato_premio": "SI - investigar bienes no inmuebles/cuentas" if candidato_premio else "NO - solo inmuebles/cuentas mencionados",
    }


def fetch_boe(fecha_inicio, fecha_fin):
    resultados = []
    d = fecha_inicio
    while d <= fecha_fin:
        fecha_str = d.strftime("%Y%m%d")
        url = f"https://www.boe.es/datosabiertos/api/boe/sumario/{fecha_str}"
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                _walk_boe(data, fecha_str, resultados)
        except requests.RequestException as e:
            print(f"[BOE] error {fecha_str}: {e}")
        time.sleep(0.4)
        d += timedelta(days=1)
    return resultados


def _walk_boe(node, fecha_str, out, contexto=None):
    contexto = contexto or {}
    if isinstance(node, dict):
        nuevo = dict(contexto)
        for campo in ("nombre", "titulo"):
            if campo in node and isinstance(node[campo], str):
                nuevo[campo] = node[campo]
        if "identificador" in node or "control" in node:
            titulo = node.get("titulo", nuevo.get("titulo", ""))
            texto = f"{titulo} {nuevo.get('nombre','')}"
            if any(k in normaliza(texto) for k in KEYWORDS_INTERES):
                out.append({
                    "fuente": "BOE", "causante": "", "dni": "", "expediente": node.get("identificador", node.get("control", "")),
                    "municipios": "", "fecha": fecha_str, "estado": clasifica_estado(texto),
                    "plazo_limite_estimado": "", "candidato_premio": "", "detalle": titulo,
                    "url": node.get("url_html", ""),
                })
        for v in node.values():
            _walk_boe(v, fecha_str, out, nuevo)
    elif isinstance(node, list):
        for elem in node:
            _walk_boe(elem, fecha_str, out, contexto)


DOG_SEARCH_URL = "https://www.xunta.gal/diario-oficial-galicia/portalPublicoBusqueda.do"

def fetch_dog(texto_busqueda="abintestato"):
    resultados = []
    params = {"lang": "es", "texto": texto_busqueda}
    try:
        resp = requests.get(DOG_SEARCH_URL, headers=HEADERS, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"[DOG] HTTP {resp.status_code}, revisar parametros de busqueda")
            return resultados
        soup = BeautifulSoup(resp.text, "lxml")
        for enlace in soup.find_all("a", href=re.compile(r"Anuncio[A-Z]")):
            href = enlace.get("href", "")
            texto = enlace.get_text(strip=True)
            if any(k in normaliza(texto) for k in KEYWORDS_INTERES) or "abintestato" in href.lower():
                url_completa = href if href.startswith("http") else f"https://www.xunta.gal{href}"
                detalle = parsea_detalle_dog(url_completa)
                fila = {
                    "fuente": "DOG", "causante": "", "dni": "", "expediente": "",
                    "municipios": "", "fecha": "", "estado": clasifica_estado(texto),
                    "plazo_limite_estimado": "", "candidato_premio": "", "detalle": texto,
                    "url": url_completa,
                }
                if detalle:
                    fila.update({
                        "causante": detalle["causante"], "dni": detalle["dni"],
                        "expediente": detalle["expediente"], "municipios": detalle["municipios"],
                        "fecha": detalle["fecha_resolucion"],
                        "plazo_limite_estimado": detalle["plazo_limite_estimado"],
                        "candidato_premio": detalle["candidato_premio"],
                    })
                resultados.append(fila)
                time.sleep(0.3)
    except requests.RequestException as e:
        print(f"[DOG] error de conexion: {e}")
    return resultados


VIGO_URL = "https://sede.vigo.org/expedientes/taboleiro/edictos.jsp"

def fetch_vigo_notarial():
    resultados = []
    try:
        resp = requests.get(VIGO_URL, headers=HEADERS, params={"org": "NOT", "lang": "es"}, timeout=20)
        if resp.status_code != 200:
            print(f"[Vigo] HTTP {resp.status_code}")
            return resultados
        soup = BeautifulSoup(resp.text, "lxml")
        tabla = soup.find("table")
        if not tabla:
            print("[Vigo] No se encontro tabla de edictos; verificar estructura HTML actual")
            return resultados
        filas = tabla.find_all("tr")[1:]
        for fila in filas:
            celdas = [c.get_text(strip=True) for c in fila.find_all("td")]
            if len(celdas) < 4:
                continue
            fecha_pub, organismo, afectado, certificado = celdas[:4]
            texto_combinado = f"{afectado} {certificado}"
            if any(k in normaliza(texto_combinado) for k in KEYWORDS_INTERES):
                resultados.append({
                    "fuente": "Tablon notarial Vigo", "causante": afectado, "dni": "", "expediente": "",
                    "municipios": "Vigo", "fecha": fecha_pub, "estado": clasifica_estado(certificado),
                    "plazo_limite_estimado": "", "candidato_premio": marca_candidato_premio(certificado),
                    "detalle": certificado, "url": VIGO_URL,
                })
    except requests.RequestException as e:
        print(f"[Vigo] error de conexion: {e}")
    return resultados


PONTEVEDRA_URL = "https://sede.pontevedra.gal/public/bulletin/bulletin-index.xhtml"

def fetch_pontevedra_tablon():
    resultados = []
    try:
        resp = requests.get(PONTEVEDRA_URL, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"[Pontevedra] HTTP {resp.status_code}")
            return resultados
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.find_all(["li", "tr", "div"], string=re.compile("abintestato|heredero|herencia", re.I)):
            texto = item.get_text(strip=True)
            resultados.append({
                "fuente": "Sede Pontevedra", "causante": "", "dni": "", "expediente": "",
                "municipios": "Pontevedra (provincia)", "fecha": "", "estado": clasifica_estado(texto),
                "plazo_limite_estimado": "", "candidato_premio": marca_candidato_premio(texto),
                "detalle": texto, "url": PONTEVEDRA_URL,
            })
    except requests.RequestException as e:
        print(f"[Pontevedra] error de conexion: {e}")
    return resultados


def main():
    hoy = date.today()
    hace_30 = hoy - timedelta(days=30)

    todos = []
    print("Consultando BOE...")
    todos += fetch_boe(hace_30, hoy)
    print("Consultando DOG (con parser de detalle)...")
    todos += fetch_dog("abintestato")
    print("Consultando tablon notarial de Vigo...")
    todos += fetch_vigo_notarial()
    print("Consultando sede de la Diputacion de Pontevedra...")
    todos += fetch_pontevedra_tablon()

    orden_prioridad = {"ABIERTO / ventana de oportunidad": 0, "SIN CLASIFICAR / revisar manualmente": 1, "CERRADO / revisar via nulidad": 2}
    todos.sort(key=lambda r: orden_prioridad.get(r.get("estado", ""), 1))

    salida = "expedientes_galicia.csv"
    campos = ["fuente", "causante", "dni", "expediente", "municipios", "fecha", "estado",
              "plazo_limite_estimado", "candidato_premio", "detalle", "url"]
    with open(salida, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=campos)
        writer.writeheader()
        for r in todos:
            writer.writerow({k: r.get(k, "") for k in campos})

    print(f"\n{len(todos)} expedientes detectados -> {salida}")
    abiertos = sum(1 for r in todos if str(r.get("estado", "")).startswith("ABIERTO"))
    premio = sum(1 for r in todos if "SI" in str(r.get("candidato_premio", "")))
    print(f"De ellos, {abiertos} en fase ABIERTA y {premio} marcados como candidatos a investigar premio por denuncia.")


if __name__ == "__main__":
    main()
