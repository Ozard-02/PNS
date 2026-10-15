from datetime import datetime, timezone

from db import (
    get_feedback_recente,
    get_feedback_statistics,
    get_feedback_da_data,
    salva_profilo,
    get_ultimo_profilo,
    get_data_ultimo_profilo,
)
from llm_client import chiama_llm

MESI_ITALIANI = [
    "", "Gennaio", "Febbraio", "Marzo", "Aprile", "Maggio", "Giugno",
    "Luglio", "Agosto", "Settembre", "Ottobre", "Novembre", "Dicembre",
]

STAGIONI = {3: "Primavera", 4: "Primavera", 5: "Primavera",
            6: "Estate", 7: "Estate", 8: "Estate",
            9: "Autunno", 10: "Autunno", 11: "Autunno",
            12: "Inverno", 1: "Inverno", 2: "Inverno"}

SYSTEM_PROMPT_AGGIORNA = """Sei un analista di preferenze musicali ed eventi. Il tuo compito è
aggiornare un "Profilo Utente" sintetico basandoti sul profilo precedente e sui nuovi
feedback dell'utente.

Regole:
- Leggi il profilo precedente e integralo con i nuovi dati, aggiornando le tendenze.
- Identifica generi/artisti/tipi di evento dove l'utente ha alzato il punteggio (graditi
  più del previsto) e dove lo ha abbassato (graditi meno).
- Cerca pattern: preferenze per location, periodi, giorni, fasce orarie deducibili.
- Descrivi l'ATMOSFERA e il CONTESTO degli eventi che piacciono all'utente
  (es. locali piccoli e intimi, atmosfera underground, festival all'aperto, serate
  informali, club, spazi autogestiti, teatro classico).
- Se emerge una preferenza per eventi economici/gratuiti o viceversa per eventi con
  biglietti costosi, segnalalo.
- Includi 3-5 KEYWORD DI RICERCA specifiche (tag/categorie) che descrivono i suoi
  interessi, da usare per cercare eventi (es. "indie", "underground",
  "elettronica","enogastronomia", "hardcore", "dj set").
- Sii OPINIONATO: parla di ciò che piace e NON piace all'utente in modo chiaro.
- NON fare riferimenti a singoli eventi specifici: parla solo di tendenze generali.
- Sii sintetico e conciso (niente fronzoli): massimo 8-10 frasi brevi, in formato elenco puntato.
- Scrivi in italiano, in terza persona (es. "L'utente apprezza particolarmente...").
- Se i nuovi feedback confermano le tendenze esistenti, limitati a rafforzarle.
- Se i nuovi feedback contraddicono il profilo precedente, dai più peso ai nuovi dati.
- NON inventare dati che non sono presenti nei feedback forniti.
- Rispondi SOLO con il profilo aggiornato, senza preamboli o commenti aggiuntivi.
"""

SYSTEM_PROMPT_INIZIALE = """Sei un analista di preferenze musicali ed eventi. Il tuo compito è
generare un "Profilo Utente" sintetico a partire dallo storico dei feedback di un utente.

Regole:
- Analizza i feedback e identifica generi/artisti/tipi di evento dove l'utente ha
  alzato o abbassato il punteggio.
- Cerca pattern: preferenze per location, periodi, giorni, fasce orarie deducibili.
- Descrivi l'ATMOSFERA e il CONTESTO degli eventi che piacciono all'utente
  (es. locali piccoli e intimi, atmosfera underground, festival all'aperto, serate
  informali, club, spazi autogestiti, teatro classico).
- Se emerge una preferenza per eventi economici/gratuiti o viceversa per eventi con
  biglietti costosi, segnalalo.
- Includi 3-5 KEYWORD DI RICERCA specifiche (tag/categorie) che descrivono i suoi
  interessi, da usare per cercare eventi (es. "indie", "underground", "jazz",
  "elettronica", "teatro sperimentale", "enogastronomia", "hardcore", "dj set").
- Sii OPINIONATO: parla di ciò che piace e NON piace all'utente in modo chiaro.
- NON fare riferimenti a singoli eventi specifici: parla solo di tendenze generali.
- Sii sintetico e conciso (niente fronzoli): massimo 8-10 frasi brevi, in formato elenco puntato.
- Scrivi in italiano, in terza persona (es. "L'utente apprezza particolarmente...").
- NON inventare dati che non sono presenti nei feedback forniti.
- Rispondi SOLO con il profilo, senza preamboli o commenti aggiuntivi.
"""


def _format_stats_per_prompt(stats: dict) -> str:
    if not stats["per_genere"]:
        return "Nessuna statistica disponibile."
    righe = ["--- STATISTICHE PER GENERE (solo nuovi feedback) ---"]
    for s in stats["per_genere"]:
        direzione = "↑" if s["avg_correzione"] > 0.5 else ("↓" if s["avg_correzione"] < -0.5 else "→")
        righe.append(
            f"- {s['genere_categoria']}: {s['count']} feedback, "
            f"media AI={s['avg_ai']}, media utente={s['avg_user']}, "
            f"correzione media={s['avg_correzione']:+0.2f} {direzione}"
        )
    tot = stats["totali"]
    righe.append(
        f"\n--- TOTALI (nuovi feedback) ---\n"
        f"Feedback totali: {tot['totale_feedback']}, "
        f"media AI globale={tot['avg_ai_globale']}, "
        f"media utente globale={tot['avg_user_globale']}, "
        f"correzione media globale={tot['avg_correzione_globale']:+0.2f}"
    )
    return "\n".join(righe)


def _format_feedback_per_prompt(feedback: list[dict]) -> str:
    if not feedback:
        return "Nessun nuovo feedback disponibile."
    righe = ["--- NUOVI FEEDBACK (dall'ultimo aggiornamento) ---"]
    for f in feedback:
        freccia = "↑" if f['punteggio_utente'] > f['punteggio_gemini'] else ("↓" if f['punteggio_utente'] < f['punteggio_gemini'] else "→")
        righe.append(
            f"- {freccia} Genere: {f['genere_categoria']} | "
            f"AI: {f['punteggio_gemini']} → Utente: {f['punteggio_utente']}"
        )
    return "\n".join(righe)


def _genera_profilo_iniziale() -> str:
    feedback = get_feedback_recente(limit=999)
    if not feedback:
        profilo = (
            f"# Profilo iniziale — nessun feedback ancora disponibile.\n\n"
            f"- Nessuna preferenza registrata: l'utente non ha ancora valutato eventi.\n"
            f"- Il profilo verrà aggiornato automaticamente dopo la prima revisione feedback."
        )
        salva_profilo(profilo)
        return profilo

    stats = get_feedback_statistics()
    feedback_testo = _format_feedback_per_prompt(feedback)
    stats_testo = _format_stats_per_prompt(stats)

    oggi = datetime.now()
    mese = MESI_ITALIANI[oggi.month]
    stagione = STAGIONI.get(oggi.month, "")
    contesto_stagionale = (
        f"\n--- CONTESTO CORRENTE ---\n"
        f"Mese: {mese} ({stagione})"
    )

    prompt = (
        f"{SYSTEM_PROMPT_INIZIALE}\n\n"
        f"{stats_testo}\n\n"
        f"{feedback_testo}\n"
        f"{contesto_stagionale}"
    )

    print("[profile_engine] Generazione profilo iniziale dal DB...")
    profilo = chiama_llm(prompt, max_tokens=2500, temperature=0.3)
    salva_profilo(profilo)
    return profilo


def aggiorna_profilo_da_feedback():
    profilo_corrente = get_ultimo_profilo()

    if profilo_corrente is None:
        _genera_profilo_iniziale()
        return

    ultimo_aggiornamento = get_data_ultimo_profilo()
    if ultimo_aggiornamento:
        nuovi_feedback = get_feedback_da_data(ultimo_aggiornamento)
    else:
        nuovi_feedback = get_feedback_recente(limit=999)

    if not nuovi_feedback:
        print("[profile_engine] Nessun nuovo feedback dall'ultimo aggiornamento. Profilo invariato.")
        return

    stats = get_feedback_statistics()
    feedback_testo = _format_feedback_per_prompt(nuovi_feedback)
    stats_testo = _format_stats_per_prompt(stats)

    oggi = datetime.now()
    mese = MESI_ITALIANI[oggi.month]
    stagione = STAGIONI.get(oggi.month, "")
    contesto_stagionale = (
        f"\n--- CONTESTO CORRENTE ---\n"
        f"Mese: {mese} ({stagione})"
    )

    prompt_completo = (
        f"{SYSTEM_PROMPT_AGGIORNA}\n\n"
        f"--- PROFILO PRECEDENTE ---\n"
        f"{profilo_corrente}\n\n"
        f"{stats_testo}\n\n"
        f"{feedback_testo}\n"
        f"{contesto_stagionale}"
    )

    print("[profile_engine] Aggiornamento profilo utente in corso...")
    nuovo_profilo = chiama_llm(prompt_completo, max_tokens=2500, temperature=0.3)
    salva_profilo(nuovo_profilo)
    print("[profile_engine] Profilo aggiornato e salvato.")


def genera_profilo_utente() -> str:
    profilo = get_ultimo_profilo()
    if profilo:
        return profilo
    return _genera_profilo_iniziale()
