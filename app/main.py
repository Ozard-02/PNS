"""
Entry point principale: eseguito ogni giorno dal cron.

Workflow:
1. Legge lo storico feedback dal DB -> genera profilo utente aggiornato (Step 2: OpenRouter, no-search)
2. Cerca eventi via fetch diretto + interpretazione OpenRouter (Step 3, unico step con internet)
3. Salva i nuovi eventi nel DB (evitando duplicati)
4. Inserisce i nuovi eventi su Google Calendar
5. Evolve i template di query in base ai feedback (Step 6, non-fatale: solo proposte)
"""
import sys
from datetime import datetime

from db import init_db, insert_evento, get_eventi_senza_calendario, update_calendar_event_id
from profile_engine import genera_profilo_utente
from search_client import cerca_eventi
from calendar_client import crea_evento_calendario
from query_engine import genera_proposte_query


def log(msg: str):
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"[{timestamp}] {msg}", flush=True)


def main():
    log("=== Avvio AI Event & Concert Tracker ===")

    init_db()

    # --- Step 2: profilo utente aggiornato (offline, no internet) ---
    log("Generazione profilo utente aggiornato dallo storico feedback...")
    try:
        profilo = genera_profilo_utente()
        log(f"Profilo generato:\n{profilo}")
    except Exception as e:
        log(f"ERRORE nella generazione del profilo: {e}")
        sys.exit(1)

    # --- Step 3: ricerca eventi (online, fetch diretto + OpenRouter) ---
    log("Ricerca eventi via web + OpenRouter...")
    try:
        eventi_trovati = cerca_eventi(profilo)
        log(f"Trovati {len(eventi_trovati)} eventi.")
    except Exception as e:
        log(f"ERRORE nella ricerca eventi: {e}")
        sys.exit(1)

    # --- Step 4: salvataggio nel DB (evitando duplicati) ---
    nuovi = 0
    for evento in eventi_trovati:
        evento_db = dict(evento)
        evento_db["punteggio_gemini"] = evento.get("punteggio_predetto")
        evento_db["data_fine"] = evento.get("data_fine")
        if insert_evento(evento_db):
            nuovi += 1
    log(f"Nuovi eventi salvati nel DB: {nuovi} (gli altri erano già presenti)")

    # --- Step 5: inserimento su Google Calendar ---
    log("Sincronizzazione con Google Calendar...")
    da_sincronizzare = get_eventi_senza_calendario()
    sincronizzati = 0
    for evento in da_sincronizzare:
        cal_id = crea_evento_calendario(evento)
        if cal_id:
            update_calendar_event_id(evento["id"], cal_id)
            sincronizzati += 1
    log(f"Eventi aggiunti a Google Calendar: {sincronizzati}")

    # --- Step 6: evoluzione query (non-fatale: un errore qui non blocca il run) ---
    log("Evoluzione template di query (solo proposte, da valutare in TUI)...")
    try:
        n_proposte = genera_proposte_query()
        log(f"Nuove proposte di query salvate: {n_proposte} "
            f"(valutale con: python /app/feedback_cli.py --proposals)")
    except Exception as e:
        log(f"AVVISO: evoluzione query saltata: {e}")

    log("=== Esecuzione completata ===")


if __name__ == "__main__":
    main()
