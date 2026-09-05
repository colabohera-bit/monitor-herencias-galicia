"""
Pipeline integrado v4 - Deteccion nacional con listas separadas por ambito
y resumen de concentracion por provincia.

Novedades v4 sobre v3:
- Ademas del CSV combinado, genera TRES listas separadas, porque cada
  administracion tiene su propio registro y estructura:
    expedientes_estatal.csv      -> BOE / Hacienda (Delegaciones de Economia y Hacienda)
    expedientes_autonomico.csv   -> Xunta de Galicia (DOG) y resto de CCAA cuando se activen
    expedientes_provincial.csv   -> Tablones notariales y de Diputacion (Vigo, Pontevedra, BOPs)
- Genera resumen_por_provincia.csv: cuenta cuantos expedientes hay por provincia
  y por estado, ordenado de mayor a menor concurrencia (donde hay mas casos).
- Genera urgentes_1_mes.csv: solo los expedientes cuyo plazo_limite_estimado
  cae dentro de los proximos 30 dias -> lista de accion inmediata.
- Todas las listas siguen ordenadas por plazo_limite_estimado ascendente.

Requisitos: pip install requests beautifulsoup4 lxml python-dateutil
Uso: python pipeline_nacional_v4.py
"""

import csv
import re
import time
import requests
from collections import Counter, defaultdict
from datetime import date, timedelta
from dateutil.relativedelta import relativedelta
from bs4 import BeautifulSoup

from fuentes_config import fuentes_activas

HEADERS = {
    "User-Agent": "monitor-herencias/1.0 (contacto@tudominio.es)",
    "Accept": "text/html,application/json",
}

KEYWORDS_ABIERTO = ["incoado", "incoacion", "incoar", "provisional", "certificado provisional", "expuesto"]
KEYWORDS_CERRADO = ["definitivo", "declara heredera", "declara heredero", "adjudicacion", "resolucion final", "unica y universal heredera"]
KEYWORDS_INTERES = ["abintestato", "herencia yacente", "heredero", "heredera", "declaracion de heredero"]
KEYWORDS_BIEN_EXCLUIDO = ["inmueble", "vivienda", "piso", "parcela", "finca", "cuenta", "deposito", "saldo bancario"]
KEYWORDS_INTERNACIONAL = ["nacionalidad", "residente en el extranjero", "consulado", "extranjero", "pasaporte"]

MESES = {
    "enero": 1, "febrero": 2, "marzo": 3, "abril": 4, "mayo": 5, "junio": 6,
    "julio": 7, "agosto": 8, "septiembre": 9, "octubre": 10, "noviembre": 11, "diciembre": 12
}

ACCION_LEGAL = {
    "ABIERTO / ventana de oportunidad": (
        "Iniciar investigacion genealogica inmediata y, si aparece candidato con indicios "
        "razonables, presentar personacion/alegacion en el expediente antes del plazo limite."
    ),
    "CERRADO / revisar via nulidad": (
        "Evaluar con el abogado colaborador la viabilidad de una accion de nulidad o revision "
        "dentro del plazo de prescripcion (art. 1963 CC), solo si aparece heredero con prueba "
        "documental solida."
    ),
    "SIN CLASIFICAR / revisar manualmente": (
        "Revisar manualmente el texto original para determinar fase real antes de decidir accion."
    ),
}

# Mapa municipio -> provincia. Ampliar conforme se detecten municipios nuevos.
MUNICIPIO_A_PROVINCIA = {
    "ourol": "Lugo", "burela": "Lugo", "viveiro": "Lugo", "monforte de lemos": "Lugo",
    "ordes": "A Coruña",
    "vilanova de arousa": "Pontevedra", "vigo": "Pontevedra", "pontevedra": "Pontevedra",
    "vilalba": "Lugo", "vilagarcia de arousa": "Pontevedra",
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
    return not any(k in t for k in KEYWORDS_BIEN_EXCLUIDO)


def marca_internacional(texto_completo):
    t = normaliza(texto_completo)
    return any(k in t for k in KEYWORDS_INTERNACIONAL)


def deduce_provincia(municipios_texto):
    t = normaliza(municipios_texto)
    for municipio, provincia in MUNICIPIO_A_PROVINCIA.items():
        if municipio in t:
            return provincia
    return "Sin determinar"


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


def fila_base(fuente, ambito):
    return {
        "fuente": fuente, "ambito": ambito, "causante": "", "dni": "", "expediente": "",
        "municipios": "", "provincia": "", "fecha": "", "estado": "", "plazo_limite_estimado": "",
        "candidato_premio": "", "internacional": "", "accion_legal": "", "detalle": "", "url": "",
    }


# ---------------------------------------------------------------------------
# BOE (ambito estatal)
# ---------------------------------------------------------------------------

def fetch_boe(cfg, fecha_inicio, fecha_fin):
    resultados = []
    d = fecha_inicio
    while d <= fecha_fin:
        fecha_str = d.strftime("%Y%m%d")
        url = cfg["url"].format(fecha=fecha_str)
        try:
            resp = requests.get(url, headers={**HEADERS, "Accept": "application/json"}, timeout=20)
            if resp.status_code == 200:
                data = resp.json()
                _walk_boe(data, fecha_str, resultados, cfg["ambito"])
        except requests.RequestException as e:
            print(f"[BOE] error {fecha_str}: {e}")
        time.sleep(0.3)
        d += timedelta(days=1)
    return resultados


def _walk_boe(node, fecha_str, out, ambito, contexto=None):
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
                fila = fila_base("BOE", ambito)
                estado = clasifica_estado(texto)
                fila.update({
                    "expediente": node.get("identificador", node.get("control", "")),
                    "fecha": fecha_str,
                    "estado": estado,
                    "candidato_premio": "SI" if marca_candidato_premio(texto) else "NO",
                    "internacional": "SI" if marca_internacional(texto) else "NO",
                    "accion_legal": ACCION_LEGAL.get(estado, ""),
                    "detalle": titulo,
                    "url": node.get("url_html", ""),
                })
                out.append(fila)
        for v in node.values():
            _walk_boe(v, fecha_str, out, ambito, nuevo)
    elif isinstance(node, list):
        for elem in node:
            _walk_boe(elem, fecha_str, out, ambito, contexto)


# ---------------------------------------------------------------------------
# DOG Galicia (ambito autonomico)
# ---------------------------------------------------------------------------

def fetch_dog(cfg, texto_busqueda="abintestato"):
    resultados = []
    params = {"lang": "es", "texto": texto_busqueda}
    try:
        resp = requests.get(cfg["url"], headers=HEADERS, params=params, timeout=20)
        if resp.status_code != 200:
            print(f"[DOG] HTTP {resp.status_code}")
            return resultados
        soup = BeautifulSoup(resp.text, "lxml")
        for enlace in soup.find_all("a", href=re.compile(r"Anuncio[A-Z]")):
            href = enlace.get("href", "")
            texto = enlace.get_text(strip=True)
            if any(k in normaliza(texto) for k in KEYWORDS_INTERES) or "abintestato" in href.lower():
                url_completa = href if href.startswith("http") else f"https://www.xunta.gal{href}"
                detalle_texto = _detalle_dog_texto(url_completa)
                fila = fila_base("DOG_GALICIA", cfg["ambito"])
                estado = clasifica_estado(texto + " " + detalle_texto)
                municipios = _extrae_municipios(detalle_texto)
                fila.update({
                    "causante": _extrae_causante(detalle_texto),
                    "dni": _extrae_dni(detalle_texto),
                    "expediente": _extrae_expediente(detalle_texto),
                    "municipios": municipios,
                    "provincia": deduce_provincia(municipios),
                    "fecha": _extrae_fecha_resolucion(detalle_texto),
                    "estado": estado,
                    "plazo_limite_estimado": _calcula_plazo(detalle_texto),
                    "candidato_premio": "SI" if marca_candidato_premio(detalle_texto) else "NO",
                    "internacional": "SI" if marca_internacional(detalle_texto) else "NO",
                    "accion_legal": ACCION_LEGAL.get(estado, ""),
                    "detalle": texto,
                    "url": url_completa,
                })
                resultados.append(fila)
                time.sleep(0.3)
    except requests.RequestException as e:
        print(f"[DOG] error: {e}")
    return resultados


def _detalle_dog_texto(url):
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            return ""
        soup = BeautifulSoup(resp.text, "lxml")
        return soup.get_text(" ", strip=True)
    except requests.RequestException:
        return ""


def _extrae_causante(texto):
    m = re.search(r"^([A-ZÁÉÍÓÚÑ][a-záéíóúñA-ZÁÉÍÓÚÑ\s]+?),\s+con\s+DNI", texto)
    return m.group(1).strip() if m else ""


def _extrae_dni(texto):
    m = re.search(r"DNI\s+([\dA-Z\-]+)", texto)
    return m.group(1) if m else ""


def _extrae_expediente(texto):
    m = re.search(r"expediente\s+([A-Z]{2,4}/\d{4}/\d+)", texto, re.IGNORECASE)
    return m.group(1) if m else ""


def _extrae_municipios(texto):
    m = re.search(r"ayuntamientos de ([^,]+(?:,[^,]+){0,3}),?\s+as[ií] como", texto)
    return m.group(1).strip() if m else ""


def _extrae_fecha_resolucion(texto):
    m = re.search(r"Compostela,\s+(\d{1,2}\s+de\s+[a-zA-Z]+\s+de\s+\d{4})", texto)
    if not m:
        return ""
    f = parsea_fecha_larga(m.group(1))
    return f.isoformat() if f else ""


def _calcula_plazo(texto):
    fecha_str = _extrae_fecha_resolucion(texto)
    if not fecha_str:
        return ""
    f = date.fromisoformat(fecha_str)
    return (f + relativedelta(years=1)).isoformat()


# ---------------------------------------------------------------------------
# Tablon notarial de Vigo (ambito provincial)
# ---------------------------------------------------------------------------

def fetch_vigo(cfg):
    resultados = []
    try:
        resp = requests.get(cfg["url"], headers=HEADERS, params={"org": "NOT", "lang": "es"}, timeout=20)
        if resp.status_code != 200:
            print(f"[Vigo] HTTP {resp.status_code}")
            return resultados
        soup = BeautifulSoup(resp.text, "lxml")
        tabla = soup.find("table")
        if not tabla:
            return resultados
        for fila_html in tabla.find_all("tr")[1:]:
            celdas = [c.get_text(strip=True) for c in fila_html.find_all("td")]
            if len(celdas) < 4:
                continue
            fecha_pub, organismo, afectado, certificado = celdas[:4]
            texto_combinado = f"{afectado} {certificado}"
            if any(k in normaliza(texto_combinado) for k in KEYWORDS_INTERES):
                fila = fila_base("TABLON_VIGO", cfg["ambito"])
                estado = clasifica_estado(certificado)
                fila.update({
                    "causante": afectado, "municipios": "Vigo", "provincia": "Pontevedra",
                    "fecha": fecha_pub, "estado": estado,
                    "candidato_premio": "SI" if marca_candidato_premio(certificado) else "NO",
                    "internacional": "SI" if marca_internacional(certificado) else "NO",
                    "accion_legal": ACCION_LEGAL.get(estado, ""),
                    "detalle": certificado, "url": cfg["url"],
                })
                resultados.append(fila)
    except requests.RequestException as e:
        print(f"[Vigo] error: {e}")
    return resultados


# ---------------------------------------------------------------------------
# Sede de la Diputacion de Pontevedra (ambito provincial)
# ---------------------------------------------------------------------------

def fetch_pontevedra(cfg):
    resultados = []
    try:
        resp = requests.get(cfg["url"], headers=HEADERS, timeout=20)
        if resp.status_code != 200:
            print(f"[Pontevedra] HTTP {resp.status_code}")
            return resultados
        soup = BeautifulSoup(resp.text, "lxml")
        for item in soup.find_all(["li", "tr", "div"], string=re.compile("abintestato|heredero|herencia", re.I)):
            texto = item.get_text(strip=True)
            fila = fila_base("SEDE_PONTEVEDRA", cfg["ambito"])
            estado = clasifica_estado(texto)
            fila.update({
                "municipios": "Pontevedra (provincia)", "provincia": "Pontevedra", "estado": estado,
                "candidato_premio": "SI" if marca_candidato_premio(texto) else "NO",
                "internacional": "SI" if marca_internacional(texto) else "NO",
                "accion_legal": ACCION_LEGAL.get(estado, ""),
                "detalle": texto, "url": cfg["url"],
            })
            resultados.append(fila)
    except requests.RequestException as e:
        print(f"[Pontevedra] error: {e}")
    return resultados


FETCHERS = {
    "BOE": lambda cfg: fetch_boe(cfg, date.today() - timedelta(days=30), date.today()),
    "DOG_GALICIA": lambda cfg: fetch_dog(cfg),
    "TABLON_VIGO": lambda cfg: fetch_vigo(cfg),
    "SEDE_PONTEVEDRA": lambda cfg: fetch_pontevedra(cfg),
}

# A que lista separada pertenece cada ambito
AMBITO_A_ARCHIVO = {
    "estatal": "expedientes_estatal.csv",
    "autonomico": "expedientes_autonomico.csv",
    "provincial": "expedientes_provincial.csv",
    "internacional": "expedientes_internacional.csv",
}

CAMPOS = ["fuente", "ambito", "causante", "dni", "expediente", "municipios", "provincia",
          "fecha", "estado", "plazo_limite_estimado", "candidato_premio", "internacional",
          "accion_legal", "detalle", "url"]


def clave_orden(fila):
    plazo = fila.get("plazo_limite_estimado") or ""
    if plazo:
        return (0, plazo)
    return (1, "9999-99-99")


def escribe_csv(nombre_archivo, filas):
    with open(nombre_archivo, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CAMPOS)
        writer.writeheader()
        for r in filas:
            writer.writerow({k: r.get(k, "") for k in CAMPOS})


def main():
    todos = []
    for nombre, cfg in fuentes_activas().items():
        if nombre not in FETCHERS:
            print(f"[{nombre}] fuente activa pero sin fetcher implementado (tipo_acceso={cfg['tipo_acceso']}) -> omitida")
            continue
        print(f"Consultando {nombre} (ambito: {cfg['ambito']})...")
        todos += FETCHERS[nombre](cfg)

    todos.sort(key=clave_orden)

    # 1) CSV combinado (todos los ambitos juntos, para vision global)
    escribe_csv("expedientes_nacional.csv", todos)

    # 2) Listas separadas por ambito (cada administracion, su propio archivo)
    por_ambito = defaultdict(list)
    for fila in todos:
        por_ambito[fila["ambito"]].append(fila)
    for ambito, nombre_archivo in AMBITO_A_ARCHIVO.items():
        escribe_csv(nombre_archivo, por_ambito.get(ambito, []))

    # 3) Resumen de concurrencia por provincia (donde hay mas casos)
    contador = Counter(f["provincia"] or "Sin determinar" for f in todos)
    contador_abiertos = Counter(f["provincia"] or "Sin determinar" for f in todos if f["estado"].startswith("ABIERTO"))
    with open("resumen_por_provincia.csv", "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["provincia", "total_expedientes", "expedientes_abiertos"])
        for provincia, total in contador.most_common():
            writer.writerow([provincia, total, contador_abiertos.get(provincia, 0)])

    # 4) Lista de urgentes: plazo dentro de los proximos 30 dias
    hoy = date.today()
    limite = hoy + timedelta(days=30)
    urgentes = [
        f for f in todos
        if f.get("plazo_limite_estimado") and hoy <= date.fromisoformat(f["plazo_limite_estimado"]) <= limite
    ]
    escribe_csv("urgentes_1_mes.csv", urgentes)

    print(f"\nTotal detectados: {len(todos)}")
    for ambito, nombre_archivo in AMBITO_A_ARCHIVO.items():
        print(f"  {ambito}: {len(por_ambito.get(ambito, []))} -> {nombre_archivo}")
    print(f"Urgentes (vencen en <= 30 dias): {len(urgentes)} -> urgentes_1_mes.csv")
    print("Resumen de concurrencia por provincia -> resumen_por_provincia.csv")


if __name__ == "__main__":
    main()
