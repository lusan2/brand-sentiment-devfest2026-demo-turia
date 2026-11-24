"""
Configuración central — demo Turia (DevFest Valencia 2026).

Versión reducida a UN único segmento: Cerveza Turia (ES · cerveza tostada/Märzen)
+ 7 competidores. Pensada para la demo pública de la charla
«Análisis de sentimiento de marca con IA por menos de 20€ al mes».
"""
import re
from dataclasses import dataclass, field
from typing import Optional

FLAGS = re.IGNORECASE | re.UNICODE

# ─────────────────────────────────────────────────────────────────────────────
# PATRÓN DE MARCA PROPIA — Cerveza Turia
# ─────────────────────────────────────────────────────────────────────────────
BRAND_PATTERNS = {
    "TURIA": re.compile(
        # (1) "cerveza/cervesa/beer Turia" (separador #/@ o espacio opcionales)
        r"\b(?:cervezas?|cerves[ae]s?|beer)(?:[\s#@]?)t[uú]rias?\b"
        # (2) "Turia tostada/Märzen/0,0/Stark/beer" (admite "#" tras Turia)
        r"|\bt[uú]rias?\s+[#]?(?:tostad[ao]|m[äa]rzen|0[\s,.]?0|stark|beer)\b"
        # (3) "Turia" desnudo con contexto cervecero (excluye "río/riu Turia")
        r"|(?<!\b(?:r[ií]o|riu)\s)\bt[uú]rias?\b"
        r"(?=[^.]{0,80}\b(?:cerves[ae]s?|cervezas?|beer|m[äa]rzen|tostad|stark|0[\s,.]?0|latas?|patrocin|sponsor|valencia\s*cf|vcf|llup)\b)",
        FLAGS,
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# PATRÓN GENÉRICO — oportunidad (categoría sin marca concreta)
# ─────────────────────────────────────────────────────────────────────────────
GENERIC_PATTERNS = {
    "ES_CERVEZA_TOSTADA": re.compile(
        r"\b(?:cervezas?|cerves[ae]s?)\s+tostad[ao]s?\b"
        r"|\b(?:cervezas?|cerves[ae]s?)\s+m[äa]rzen\b"
        r"|\btoasted\s+beer\b"
        r"|\bm[äa]rzen\s+(?:beer|cerveza)\b"
        r"|\btostad[ao]s?\s+(?:0[\s,.]?0|beer|m[äa]rzen)\b",
        FLAGS,
    ),
}

# ─────────────────────────────────────────────────────────────────────────────
# PATRONES DE COMPETIDORES (7)
# ─────────────────────────────────────────────────────────────────────────────
TURIA_COMPETITOR_PATTERNS = {
    "amstel_oro":         re.compile(r"\bamstel(?:\s+oro)?\b", FLAGS),
    # "San Miguel" solo cuenta si es la cerveza Selecta (o con contexto cervecero/ES).
    # Evita falsos positivos: topónimo "San Miguel" (El Salvador), San Miguel Arcángel,
    # "San Miguel Beer"/Beermen (Filipinas), Viñedo/Mercado de San Miguel, etc.
    "san_miguel_selecta": re.compile(
        r"\bsan\s+miguel[\s-]*selecta\b"
        r"|\bsan\s+miguel\b(?=[^.\n]{0,60}\b(?:selecta|cervezas?|cerves[ae]s?|lager|m[äa]rzen(?:bier)?|tostad[ao]|1516|0[\s,.]?0)\b)",
        FLAGS,
    ),
    # "1906" solo cuenta si va calificado como cerveza (Reserva Especial / Red / Black Coupage /
    # La Milnueve / lager) o precedido de palabra cervecera. Evita falsos positivos del AÑO 1906.
    "1906":               re.compile(
        r"\b1906\b[\s-]*(?:reserva(?:\s+especial)?|red(?:\s+vintage)?|black(?:\s+coupage)?|coupage|vintage|milnueve|mil\s+nueve|lager)\b"
        r"|\b(?:cervezas?|cerves[ae]s?|beers?|lagers?|estrella\s+galicia)\b[\s+-]*1906\b",
        FLAGS,
    ),
    # "Mahou" puede ser la marca de cerveza ES O el japonés 魔法 (magia, anime).
    # Excluimos compuestos japoneses (Mahou Shoujo / Sentai / no Shimai / Tsukai...).
    "mahou_maestra":      re.compile(
        r"\bmahou\b"
        r"(?!\s+(?:sh[oō]ujo|shoujo|sentai|tsukai|ky[oō]u|kyou|sh[oō]unen|shounen|gakuen|senshi|no\b))"
        r"(?:\s+maestra(?:\s+doble\s+l[úu]pulo)?)?\b",
        FLAGS,
    ),
    "alhambra_reserva":   re.compile(r"\balhambra(?:\s+reserva(?:\s+1925)?)?\b", FLAGS),
    "cruzcampo_tostada":  re.compile(r"\bcruzcampo\s+gran\s+reserva\b", FLAGS),
    "moritz_epidor":      re.compile(r"\bmoritz\s+epidor\b", FLAGS),
}

# ─────────────────────────────────────────────────────────────────────────────
# BIRRAPEDIA — cervezas a monitorizar (slug, id, nombre).
# El rating (0-5) + nº de valoraciones sale del JSON-LD de la ficha.
# ─────────────────────────────────────────────────────────────────────────────
BIRRAPEDIA_BEERS = {
    "TURIA": [
        ("turia-marzen", "527f4e4fd187e40109001053", "Turia Märzen"),
        ("turia-stark", "68dabed61603daf628686da4", "Turia Stark"),
        ("turia-00-tostada", "67bdafeb1603da6c6bd255dc", "Turia 0,0 Tostada"),
        ("cruzcampo-gran-reserva", "527f4e53d187e401090022ab", "Cruzcampo Gran Reserva"),
        ("moritz-epidor", "527f4e55d187e40109002cb5", "Moritz Epidor"),
    ],
}

# ─────────────────────────────────────────────────────────────────────────────
# CANALES DE YOUTUBE
# En la demo Turia no se clasifican canales (tabla vacía). `classify_channel`
# sigue importándola por contrato, pero siempre devuelve None.
# ─────────────────────────────────────────────────────────────────────────────
YOUTUBE_CHANNELS = {}

# ─────────────────────────────────────────────────────────────────────────────
# CONFIGURACIÓN DE SEGMENTOS
# ─────────────────────────────────────────────────────────────────────────────
@dataclass
class SegmentConfig:
    brand: str
    market: str
    segment: str
    language: str
    brand_pattern_key: str
    generic_pattern_key: str
    competitor_keys: list
    base_search_terms: list
    subreddits: list
    newsapi_language: str
    newsapi_country: Optional[str] = None
    google_news_country: Optional[str] = None
    youtube_terms: list = field(default_factory=list)

    @property
    def competitor_patterns(self) -> dict:
        pool = TURIA_COMPETITOR_PATTERNS if self.brand == "TURIA" else {}
        return {k: pool[k] for k in self.competitor_keys if k in pool}

    @property
    def brand_pattern(self):
        return BRAND_PATTERNS[self.brand_pattern_key]

    @property
    def generic_pattern(self):
        return GENERIC_PATTERNS[self.generic_pattern_key]


SEGMENTS: list[SegmentConfig] = [
    SegmentConfig(
        brand="TURIA",
        market="ES",
        segment="cerveza-tostada",
        language="es",
        brand_pattern_key="TURIA",
        generic_pattern_key="ES_CERVEZA_TOSTADA",
        competitor_keys=["amstel_oro", "san_miguel_selecta", "1906", "mahou_maestra", "alhambra_reserva", "cruzcampo_tostada", "moritz_epidor"],
        base_search_terms=[
            "cerveza Turia", "cervesa Turia", "Turia tostada", "Turia Märzen", "Turia Marzen",
            "Turia 0,0", "Turia Stark", "Turia beer", "Turia toasted beer", "Turia Märzen beer",
            "cerveza tostada", "cerveza Märzen", "toasted beer Spain", "Märzen beer",
            "Amstel Oro", "San Miguel Selecta", "1906 Reserva Especial",
            "Mahou Maestra", "Alhambra Reserva 1925", "Cruzcampo Gran Reserva", "Moritz Epidor",
        ],
        subreddits=["Cerveza", "Spain", "Valencia", "beer", "askspain"],
        newsapi_language="es",
        newsapi_country="es",
        google_news_country="ES",
        youtube_terms=[
            "cerveza Turia", "Turia tostada", "Turia Märzen", "Turia beer", "cervesa Turia",
            "cerveza tostada", "cerveza Märzen",
            "Amstel Oro", "San Miguel Selecta", "1906 Reserva Especial",
            "Mahou Maestra", "Alhambra Reserva 1925", "Cruzcampo Gran Reserva", "Moritz Epidor",
            "mejor cerveza tostada", "cata cerveza tostada",
        ],
    ),
]

# ─────────────────────────────────────────────────────────────────────────────
# GENERACIÓN DE VARIANTES DE KEYWORDS
# ─────────────────────────────────────────────────────────────────────────────
def generate_variants(base_terms: list[str]) -> list[str]:
    """Genera todas las combinaciones posibles de cada término base."""
    variants: set[str] = set()
    for term in base_terms:
        t = term.strip().lower()
        variants.add(t)
        variants.add(t.replace(" ", "-"))     # con guion
        variants.add(t.replace("-", " "))     # con espacio
        variants.add(t.replace(" ", ""))      # sin separador
    return sorted(variants)


def build_batched_queries(variants: list[str], max_len: int = 450) -> list[str]:
    """Agrupa variantes en queries que caben en el límite de la API."""
    batches: list[str] = []
    current: list[str] = []
    current_len = 0

    for v in variants:
        token = f'"{v}"' if " " in v else v
        chunk_len = len(token) + (4 if current else 0)  # 4 = len(" OR ")
        if current and current_len + chunk_len > max_len:
            batches.append(" OR ".join(current))
            current = [token]
            current_len = len(token)
        else:
            current.append(token)
            current_len += chunk_len

    if current:
        batches.append(" OR ".join(current))

    return batches
