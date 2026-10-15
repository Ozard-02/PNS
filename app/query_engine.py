"""
Unica responsabilità: far evolvere i template di query in base ai feedback.

Genera PROPOSTE (mai applicate in automatico): l'utente le valuta con
feedback_cli.py --proposals e quelle accettate riscrivono /data/query_templates.txt.
"""
import json

import requests

from db import (
    get_feedback_da_data,
    get_feedback_recente,
    get_ultimo_profilo,
    get_stats_per_query,
    salva_proposta,
    conta_proposte_pending,
    get_data_ultima_proposta,
)
from llm_client import chiama_llm, LLMResponseError, QuotaGiornalieraEsaurita
from query_store import carica_template, template_valido, MAX_LEN_TEMPLATE
from search_client import _estrai_json

MIN_NUOVI_FEEDBACK = 3
MAX_PROPOSTE = 3


def _formatta_template_con_stats(template: list[str], stats: list[dict]) -> str:
    per_template = {s["query_origine"]: s for s in stats}
    righe = []
    for i, t in enumerate(template, 1):
        s = per_template.get(t)
        if s:
            righe.append(
                f"{i}. `{t}`  [eventi trovati: {s['n_eventi']}, "
                f"valutati: {s['n_valutati']}, media voti utente: {s['avg_user']}]"
            )
        else:
            righe.append(f"{i}. `{t}`  [ancora nessun evento tracciato]")
    return "\n".join(righe)


def _formatta_feedback(feedback: list[dict]) -> str:
    piaciuti = [f for f in feedback if (f.get("punteggio_utente") or 0) >= 7][:8]
    bocciati = [f for f in feedback if (f.get("punteggio_utente") or 10) <= 4][:8]
    righe = ["Eventi PIACIUTI (voto utente >= 7):"]
    righe += [f"- {f['titolo']} ({f.get('genere_categoria') or '?'}, voto {f['punteggio_utente']})"
              for f in piaciuti] or ["- nessuno"]
    righe.append("Eventi BOCCIATI (voto utente <= 4):")
    righe += [f"- {f['titolo']} ({f.get('genere_categoria') or '?'}, voto {f['punteggio_utente']})"
              for f in bocciati] or ["- nessuno"]
    return "\n".join(righe)


def _normalizza_proposta(p: dict) -> dict | None:
    """Mappa varianti di schema (template/query, azione/index) al formato interno.

    I modelli free non sempre rispettano i nomi di campo richiesti: invece di
    scartare tutto, normalizziamo le varianti più comuni.
    """
    if not isinstance(p, dict):
        return None
    template = p.get("template") or p.get("query") or ""
    motivazione = p.get("motivazione") or p.get("reason") or ""
    azione = p.get("azione")
    indice = p.get("indice")
    if not isinstance(indice, int):
        indice = p.get("index")
    if azione not in ("aggiungi", "sostituisci"):
        azione = "sostituisci" if isinstance(indice, int) else "aggiungi"
    return {
        "azione": azione,
        "template": template,
        "motivazione": motivazione,
        "indice": indice if azione == "sostituisci" else None,
    }


def _proposta_valida(p: dict, n_template: int) -> bool:
    if not isinstance(p, dict):
        return False
    if p.get("azione") not in ("aggiungi", "sostituisci"):
        return False
    if not template_valido(p.get("template", "")):
        return False
    if "{location}" not in p["template"]:
        print(f"[query_engine] Scartata: manca il placeholder {{location}}: {p['template'][:60]}")
        return False
    if p["azione"] == "sostituisci":
        idx = p.get("indice")
        if not isinstance(idx, int) or not (1 <= idx <= n_template):
            return False
    return True


def genera_proposte_query(force: bool = False) -> int:
    """Genera proposte di query se ci sono abbastanza nuovi feedback. Ritorna n. salvate."""
    if not force and conta_proposte_pending() > 0:
        print("[query_engine] Ci sono già proposte in attesa di valutazione: niente di nuovo.")
        return 0

    ultima = get_data_ultima_proposta()
    nuovi = get_feedback_da_data(ultima) if ultima else get_feedback_recente(limit=999)
    if not force and len(nuovi) < MIN_NUOVI_FEEDBACK:
        print(f"[query_engine] Solo {len(nuovi)} nuovi feedback (minimo {MIN_NUOVI_FEEDBACK}): niente di nuovo.")
        return 0

    template = carica_template()
    stats = get_stats_per_query()
    profilo = get_ultimo_profilo() or "(profilo non ancora disponibile)"
    profilo = profilo[:800]

    prompt = f"""Sei un esperto di ricerca web per eventi locali. Migliora le query usate per
cercare eventi, basandoti sui gusti dell'utente e sui risultati passati di ogni query.

Profilo utente:
{profilo}

Query attuali (numerate) con statistiche:
{_formatta_template_con_stats(template, stats)}

Feedback recenti:
{_formatta_feedback(nuovi)}

Proponi fino a {MAX_PROPOSTE} modifiche. Per ciascuna rispondi con un oggetto JSON:
- {{"azione": "aggiungi", "template": "...", "motivazione": "..."}} per una NUOVA query
  utile a trovare eventi piaciuti e finora mancati;
- {{"azione": "sostituisci", "indice": N, "template": "...", "motivazione": "..."}} per
  RIMPIAZZARE la query N (solo se ha statistiche deboli: pochi eventi o voti bassi).

Regole per i template:
- OGNI template DEVE contenere il placeholder {{location}}.
- Usa solo questi placeholder: {{location}} {{mese_anno}} {{oggi}} {{fine}}.
- Massimo {MAX_LEN_TEMPLATE} caratteri, niente date scritte a mano (solo placeholder).
- BREVITÀ OBBLIGATORIA: tieni ogni template sotto ~60 caratteri + placeholder (query lunghe rese oltre ~90 caratteri vengono bloccate da DuckDuckGo e non trovano nulla).
- Se tutto funziona già bene, puoi proporre meno di {MAX_PROPOSTE} modifiche.
- Motivazioni concise: una sola frase ciascuna, niente fronzoli.
- Usa ESATTAMENTE questi nomi di campo (azione, template, indice, motivazione), nessun altro.

Rispondi ESCLUSIVAMENTE con un array JSON (nessun testo prima o dopo, nessun blocco markdown).
"""

    print("[query_engine] Generazione proposte in corso...")
    try:
        testo_risposta = chiama_llm(prompt, max_tokens=4000, temperature=0.3)
    except QuotaGiornalieraEsaurita as e:
        print(f"[query_engine] {e}")
        return 0
    except (LLMResponseError, requests.HTTPError) as e:
        print(f"[query_engine] LLM non disponibile ({e}), niente di nuovo.")
        return 0
    try:
        proposte_grezze = _estrai_json(testo_risposta)
    except (json.JSONDecodeError, IndexError) as e:
        print(f"[query_engine] Risposta del modello non utilizzabile ({e}), niente di nuovo.")
        print(f"[query_engine] Risposta grezza:\n{testo_risposta[:500]}")
        return 0
    if not isinstance(proposte_grezze, list):
        print("[query_engine] La risposta non è una lista JSON, niente di nuovo.")
        return 0

    salvate = 0
    for grezza in proposte_grezze[:MAX_PROPOSTE]:
        p = _normalizza_proposta(grezza)
        if p is None or not _proposta_valida(p, len(template)):
            print(f"[query_engine] Proposta non valida, scartata: {str(grezza)[:100]}")
            continue
        salva_proposta(
            template=p["template"].strip(),
            motivazione=(p.get("motivazione") or "").strip()[:500],
            azione=p["azione"],
            indice_target=p.get("indice") if p["azione"] == "sostituisci" else None,
        )
        salvate += 1

    print(f"[query_engine] Salvate {salvate} nuove proposte (valutale con feedback_cli.py --proposals).")
    return salvate
