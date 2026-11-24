"""
Clasifica un texto en: brand | competitor | opportunity | irrelevant
y extrae todas las entidades mencionadas.
"""
from config import BRAND_PATTERNS, GENERIC_PATTERNS, YOUTUBE_CHANNELS, SegmentConfig
import unicodedata


def match(text: str, segment: SegmentConfig) -> dict:
    """
    Analiza el texto y devuelve:
    {
        "mention_type": "brand" | "competitor" | "opportunity" | None,
        "entity": str | None,          # entidad principal
        "all_entities": list[str],     # todas las entidades detectadas
    }
    Prioridad: brand > competitor > opportunity
    """
    combined = _combined_text(text)
    all_entities: list[str] = []
    primary_type: str | None = None
    primary_entity: str | None = None

    # 1. ¿Menciona la marca propia?
    if segment.brand_pattern.search(combined):
        primary_type = "brand"
        primary_entity = segment.brand
        all_entities.append(segment.brand)

    # 2. ¿Menciona algún competidor?
    for name, pattern in segment.competitor_patterns.items():
        if pattern.search(combined):
            all_entities.append(name)
            if primary_type is None:
                primary_type = "competitor"
                primary_entity = name

    # 3. ¿Solo menciona el producto genérico?
    if primary_type is None and segment.generic_pattern.search(combined):
        primary_type = "opportunity"
        primary_entity = None

    return {
        "mention_type": primary_type,
        "entity": primary_entity,
        "all_entities": list(dict.fromkeys(all_entities)),  # dedup, mantiene orden
    }


def _combined_text(text: str) -> str:
    """Limpia y normaliza para el matching (sin alterar el original)."""
    return " ".join(text.split())


def _norm(s: str) -> str:
    """Normaliza para matching de nombres de canal: minúsculas, sin acentos."""
    s = s.lower().strip()
    s = unicodedata.normalize('NFD', s)
    s = ''.join(c for c in s if unicodedata.category(c) != 'Mn')
    return s


def classify_channel(author: str, market: str) -> str | None:
    """
    Clasifica un canal de YouTube por tipo: 'competidor' | 'afin' | None.

    Se usa la tabla YOUTUBE_CHANNELS por mercado. El matching es por subcadena
    normalizada sobre el nombre del canal (channelTitle → author).
    La prioridad es competidor > afin (un canal de competidor NUNCA se marca afín).
    """
    if not author or not market:
        return None
    name = _norm(author)
    table = YOUTUBE_CHANNELS.get(market, {})
    for kw in table.get("competidor", []):
        if _norm(kw) in name:
            return "competidor"
    for kw in table.get("afin", []):
        if _norm(kw) in name:
            return "afin"
    return None
