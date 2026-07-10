"""
Entry point principale: eseguito ogni giorno dal cron.

Workflow:
1. Legge lo storico feedback dal DB -> genera profilo utente aggiornato (Step 2: Groq o Gemini no-search)
2. Cerca eventi con Gemini + Google Search Grounding (Step 3, unico step con internet)
3. Salva i nuovi eventi nel DB (evitando duplicati)
4. Inserisce i nuovi eventi su Google Calendar
"""
import sys
from datetime import datetime

from db import init_db, insert_evento, get_eventi_senza_calendario, update_calendar_event_id
from profile_engine import genera_profilo_utente
from search_client import cerca_eventi
from calendar_client import crea_evento_calendario


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

    # --- Step 3: ricerca eventi (online, Gemini + Google Search) ---
    log("Ricerca eventi tramite Gemini + Google Search Grounding...")
    try:
        eventi_trovati = cerca_eventi(profilo)
        log(f"Trovati {len(eventi_trovati)} eventi.")
    except Exception as e:
        log(f"ERRORE nella ricerca eventi: {e}")
        sys.exit(1)

    # --- Step 4: salvataggio nel DB (evitando duplicati) ---
    nuovi = 0
    for evento in eventi_trovati:
        # normalizza chiave per il DB (punteggio_gemini invece di punteggio_predetto)
        evento_db = dict(evento)
        evento_db["punteggio_gemini"] = evento.get("punteggio_predetto")
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

    log("=== Esecuzione completata ===")


if __name__ == "__main__":
    main()
