"""
Unica responsabilità: caricamento/salvataggio dei template di query di ricerca.

I template vivono in un file di testo (default /data/query_templates.txt, persistente
sul volume Docker): una riga = un template, righe vuote e righe '#' = commenti.
Placeholder ammessi: {location} {mese_anno} {oggi} {fine}.

Al primo run il file viene creato con i default. Il file è input esterno
(editabile dall'utente, riscrivibile dalle proposte accettate in TUI): ogni riga
viene validata prima dell'uso e quelle non valide sono scartate con un warning.
"""
import os
import re
from datetime import datetime, timedelta

from config import QUERY_TEMPLATES_PATH, LOCATION, SEARCH_RADIUS_DAYS

PLACEHOLDER_AMMESSI = ("location", "mese_anno", "oggi", "fine")
MAX_TEMPLATE = 10
MAX_LEN_TEMPLATE = 300

DEFAULT_TEMPLATES = [
    # Brevi di proposito: query lunghe (>~90 char renderizzate) provocano la
    # pagina challenge di DuckDuckGo (HTTP 202) e zero risultati.
    "concerti spettacoli teatro {location} {mese_anno}",
    "eventi underground indie {location} {mese_anno}",
    "sagre mostre mercatini {location} {mese_anno}",
]

SEED_HEADER = """# Template di ricerca eventi: una riga = una query.
# Placeholder ammessi: {location} {mese_anno} {oggi} {fine}.
# Tienili BREVI (meglio <60 caratteri + placeholder): query lunghe vengono
# bloccate da DuckDuckGo (HTTP 202) e non trovano nulla.
# Puoi modificare questo file a mano oppure valutare le proposte del modello con:
#   docker exec -it ai-event-tracker python /app/feedback_cli.py --proposals
"""

_pattern_placeholder = re.compile(r"\{([^{}]+)\}")


def template_valido(template: str) -> bool:
    """Una riga è un template valido se non vuota, entro i limiti e con soli placeholder noti."""
    t = (template or "").strip()
    if not t or len(t) > MAX_LEN_TEMPLATE:
        return False
    for nome in _pattern_placeholder.findall(t):
        if nome not in PLACEHOLDER_AMMESSI:
            return False
    return True


def carica_template(path: str = QUERY_TEMPLATES_PATH) -> list[str]:
    """Legge i template dal file; se manca, lo crea con i default. Mai ritorna lista vuota."""
    if not os.path.exists(path):
        try:
            with open(path, "w", encoding="utf-8") as f:
                f.write(SEED_HEADER + "\n".join(DEFAULT_TEMPLATES) + "\n")
            print(f"[query_store] File template creato con i default: {path}")
        except OSError as e:
            print(f"[query_store] Impossibile creare {path}: {e}. Uso i default in memoria.")
            return list(DEFAULT_TEMPLATES)

    try:
        with open(path, encoding="utf-8") as f:
            righe = [r.strip() for r in f]
    except OSError as e:
        print(f"[query_store] Impossibile leggere {path}: {e}. Uso i default in memoria.")
        return list(DEFAULT_TEMPLATES)

    utili = [r for r in righe if r and not r.startswith("#")]
    template = [r for r in utili if template_valido(r)][:MAX_TEMPLATE]
    scartate = len(utili) - len(template)
    if scartate > 0:
        print(f"[query_store] Scartate {scartate} righe non valide (max {MAX_TEMPLATE}, "
              f"max {MAX_LEN_TEMPLATE} char, placeholder {PLACEHOLDER_AMMESSI}).")
    if not template:
        print("[query_store] Nessun template valido: uso i default in memoria.")
        return list(DEFAULT_TEMPLATES)
    return template


def salva_template(template: list[str], path: str = QUERY_TEMPLATES_PATH) -> list[str]:
    """Valida e scrive i template nel file. Ritorna quelli scritti; errore se nessuno valido."""
    puliti = [t.strip() for t in template if template_valido(t)][:MAX_TEMPLATE]
    if not puliti:
        raise ValueError("Nessun template valido: il file non è stato modificato.")
    with open(path, "w", encoding="utf-8") as f:
        f.write(SEED_HEADER + "\n".join(puliti) + "\n")
    return puliti


def render_template(template: str) -> str:
    """Sostituisce i placeholder noti con i valori correnti (replace, non format: robusto a typo)."""
    oggi_dt = datetime.now()
    fine_dt = oggi_dt + timedelta(days=SEARCH_RADIUS_DAYS)
    valori = {
        "location": LOCATION,
        "mese_anno": oggi_dt.strftime("%B %Y"),
        "oggi": oggi_dt.strftime("%Y-%m-%d"),
        "fine": fine_dt.strftime("%Y-%m-%d"),
    }
    out = template
    for nome, valore in valori.items():
        out = out.replace("{" + nome + "}", valore)
    return re.sub(r"\s+", " ", out).strip()


def build_queries(path: str = QUERY_TEMPLATES_PATH) -> list[tuple[str, str]]:
    """Ritorna coppie (template, query renderizzata) per ogni template valido."""
    return [(t, render_template(t)) for t in carica_template(path)]
