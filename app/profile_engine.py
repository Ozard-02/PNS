from datetime import datetime, timezone

from db import (
    get_feedback_recente,
    get_feedback_statistics,
    get_feedback_da_data,
    salva_profilo,
    get_ultimo_profilo,
)
from config import PROFILE_ENGINE, PROFILE_FILE_PATH, PROFILE_HISTORY_PATH

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
- Sii sintetico: massimo 8-10 frasi, in formato elenco puntato.
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
- Sii sintetico: massimo 8-10 frasi, in formato elenco puntato.
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


def _genera_con_gemini(prompt_completo: str) -> str:
    from google import genai
    from config import GEMINI_API_KEY, GEMINI_PROFILE_MODEL

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_PROFILE_MODEL,
        contents=prompt_completo,
    )
    return response.text.strip()


def _genera_con_groq(prompt_completo: str) -> str:
    from groq import Groq
    from config import GROQ_API_KEY, GROQ_MODEL

    client = Groq(api_key=GROQ_API_KEY)
    parts = prompt_completo.split("--- STATISTICHE", 1)
    if len(parts) == 2:
        system_content = parts[0].strip()
        user_content = "--- STATISTICHE" + parts[1]
    else:
        system_content = prompt_completo
        user_content = prompt_completo

    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": system_content},
            {"role": "user", "content": user_content},
        ],
        temperature=0.3,
        max_tokens=500,
    )
    return completion.choices[0].message.content.strip()


def _chiama_llm(prompt: str) -> str:
    if PROFILE_ENGINE == "groq":
        return _genera_con_groq(prompt)
    elif PROFILE_ENGINE == "gemini":
        return _genera_con_gemini(prompt)
    else:
        raise ValueError(f"PROFILE_ENGINE non valido: {PROFILE_ENGINE!r} (usa 'gemini' o 'groq')")


def _timestamp_da_file(contenuto: str) -> str | None:
    """Legge la data dell'ultimo aggiornamento dalla prima riga del profilo."""
    prima_riga = contenuto.strip().split("\n")[0] if contenuto else ""
    if prima_riga.startswith("# Aggiornato:"):
        return prima_riga.split("# Aggiornato:", 1)[1].strip()
    return None


def leggi_profilo_da_file() -> str:
    """Legge il profilo utente dal file. Se non esiste, lo genera dal DB."""
    try:
        with open(PROFILE_FILE_PATH, "r") as f:
            contenuto = f.read().strip()
        if contenuto:
            return contenuto
    except (FileNotFoundError, IOError):
        pass
    return _genera_profilo_iniziale()


def _genera_profilo_iniziale() -> str:
    """Genera il primo profilo: se ci sono feedback nel DB li usa, altrimenti neutro."""
    feedback = get_feedback_recente(limit=999)
    if not feedback:
        now = datetime.now(timezone.utc)
        profilo = (
            f"# Aggiornato: {now.isoformat()}\n"
            f"# Profilo iniziale — nessun feedback ancora disponibile.\n\n"
            f"- Nessuna preferenza registrata: l'utente non ha ancora valutato eventi.\n"
            f"- Il profilo verrà aggiornato automaticamente dopo la prima revisione feedback."
        )
        with open(PROFILE_FILE_PATH, "w") as f:
            f.write(profilo + "\n")
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
    profilo = _chiama_llm(prompt)
    scrivi_profilo(profilo)
    salva_profilo(profilo)
    return profilo


def archivia_profilo_precedente(profilo_precedente: str):
    """Prepend il profilo precedente in profilo_storico.txt con header data."""
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")
    header = f"\n\n=== Profilo - {now} ===\n"
    try:
        with open(PROFILE_HISTORY_PATH, "r") as f:
            storico = f.read()
    except (FileNotFoundError, IOError):
        storico = ""
    with open(PROFILE_HISTORY_PATH, "w") as f:
        f.write(header + profilo_precedente + storico)


def scrivi_profilo(contenuto: str):
    """Sovrascrive profilo_utente.txt con il nuovo contenuto, aggiungendo timestamp."""
    now = datetime.now(timezone.utc)
    with open(PROFILE_FILE_PATH, "w") as f:
        f.write(f"# Aggiornato: {now.isoformat()}\n")
        f.write(contenuto if contenuto.endswith("\n") else contenuto + "\n")


def aggiorna_profilo_da_feedback():
    """Legge i nuovi feedback dall'ultimo aggiornamento e aggiorna il profilo."""
    profilo_corrente = leggi_profilo_da_file()
    ultimo_aggiornamento = _timestamp_da_file(profilo_corrente)

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
    nuovo_profilo = _chiama_llm(prompt_completo)

    archivia_profilo_precedente(profilo_corrente)
    scrivi_profilo(nuovo_profilo)

    salva_profilo(nuovo_profilo)
    print("[profile_engine] Profilo aggiornato e salvato.")


def genera_profilo_utente() -> str:
    """Wrapper per main.py: restituisce il profilo corrente dal file."""
    return leggi_profilo_da_file()


def get_profilo_corrente() -> str:
    profilo = get_ultimo_profilo()
    if profilo:
        return profilo
    return "Nessun profilo storico disponibile ancora: prima esecuzione del sistema."
