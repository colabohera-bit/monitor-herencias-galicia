"""
fuentes_config.py
Registro configurable de fuentes de boletines oficiales en Espana.
Para anadir un boletin nuevo, solo hay que anadir una entrada al diccionario FUENTES.
No hace falta tocar el resto del pipeline.

Cada fuente tiene:
- ambito: "estatal" | "autonomico" | "provincial" | "internacional"
- tipo_acceso: "api" (tiene API oficial como el BOE) | "html" (hay que parsear HTML) | "pendiente" (aun no configurado)
- url: URL base de consulta
- activo: True/False -> permite activar/desactivar fuentes sin borrarlas
"""

FUENTES = {
    "BOE": {
        "ambito": "estatal",
        "tipo_acceso": "api",
        "url": "https://www.boe.es/datosabiertos/api/boe/sumario/{fecha}",
        "activo": True,
        "notas": "API oficial JSON, cubre expedientes abintestato a favor del Estado (vecindad civil comun).",
    },
    "DOG_GALICIA": {
        "ambito": "autonomico",
        "tipo_acceso": "html",
        "url": "https://www.xunta.gal/diario-oficial-galicia/portalPublicoBusqueda.do",
        "activo": True,
        "notas": "Xunta de Galicia, Ley 2/2006 y Ley 6/2023. Fase piloto y prioritaria.",
    },
    "TABLON_VIGO": {
        "ambito": "provincial",
        "tipo_acceso": "html",
        "url": "https://sede.vigo.org/expedientes/taboleiro/edictos.jsp",
        "activo": True,
        "notas": "Edictos notariales, fase mas temprana del circuito, antes de Hacienda/Xunta.",
    },
    "SEDE_PONTEVEDRA": {
        "ambito": "provincial",
        "tipo_acceso": "html",
        "url": "https://sede.pontevedra.gal/public/bulletin/bulletin-index.xhtml",
        "activo": True,
        "notas": "Tablon de anuncios de la Diputacion de Pontevedra.",
    },

    # --- Fase 2: comarcas limitrofes con perfil similar (rural + emigracion) ---
    "BOPA_ASTURIAS": {
        "ambito": "autonomico",
        "tipo_acceso": "pendiente",
        "url": "https://www.asturias.es/bopa",
        "activo": False,
        "notas": "Activar en fase 2. Perfil similar a Galicia (rural, emigracion historica).",
    },
    "BOCYL": {
        "ambito": "autonomico",
        "tipo_acceso": "pendiente",
        "url": "https://bocyl.jcyl.es",
        "activo": False,
        "notas": "Boletin Oficial de Castilla y Leon. Activar en fase 2.",
    },

    # --- Fase 3: resto de comunidades autonomas (placeholders, activar progresivamente) ---
    "BOJA_ANDALUCIA": {"ambito": "autonomico", "tipo_acceso": "pendiente", "url": "https://www.juntadeandalucia.es/boja", "activo": False, "notas": "Fase 3."},
    "BOA_ARAGON": {"ambito": "autonomico", "tipo_acceso": "pendiente", "url": "https://www.boa.aragon.es", "activo": False, "notas": "Fase 3."},
    "DOGC_CATALUNYA": {"ambito": "autonomico", "tipo_acceso": "pendiente", "url": "https://dogc.gencat.cat", "activo": False, "notas": "Fase 3."},
    "BOCM_MADRID": {"ambito": "autonomico", "tipo_acceso": "pendiente", "url": "https://www.bocm.es", "activo": False, "notas": "Fase 3."},
    "BOPV_EUSKADI": {"ambito": "autonomico", "tipo_acceso": "pendiente", "url": "https://www.euskadi.eus/bopv2", "activo": False, "notas": "Fase 3."},
    # Anadir aqui el resto de comunidades cuando toque activarlas (Baleares, Canarias, Cantabria,
    # Castilla-La Mancha, C. Valenciana, Extremadura, Murcia, Navarra, La Rioja).

    # --- Ambito internacional: no es un boletin, es un marcador de complejidad legal ---
    "INTERNACIONAL_UE650_2012": {
        "ambito": "internacional",
        "tipo_acceso": "pendiente",
        "url": "",
        "activo": False,
        "notas": (
            "No es una fuente de scraping. Es un marcador: cuando un expediente detectado "
            "menciona causante o heredero de nacionalidad extranjera, o bienes en el extranjero, "
            "aplica el Reglamento (UE) 650/2012 y puede requerir Certificado Sucesorio Europeo. "
            "Requiere abogado especializado en derecho internacional privado, no solo derecho civil espanol."
        ),
    },
}


def fuentes_activas(ambito=None):
    """Devuelve las fuentes activas, opcionalmente filtradas por ambito."""
    return {
        nombre: cfg for nombre, cfg in FUENTES.items()
        if cfg["activo"] and (ambito is None or cfg["ambito"] == ambito)
    }
