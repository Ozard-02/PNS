"""
Script di TEST LOCALE (senza Docker) per verificare che la chiamata a Gemini
con Google Search Grounding funzioni correttamente.

Non tocca il database né Google Calendar: stampa solo il risultato a schermo.

Uso:
    1. pip install -r requirements.txt
    2. export GEMINI_API_KEY="la-tua-chiave"   (oppure crea un file .env e usa python-dotenv)
    3. python test_search_locale.py
"""
import os
import sys
import json

# Permette di caricare le variabili da un file .env se presente (opzionale)
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # se non hai python-dotenv installato, usa export manuale delle variabili

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "app"))

from search_client import cerca_eventi  # noqa: E402


def main():
    if not os.getenv("GEMINI_API_KEY"):
        print("ERRORE: variabile GEMINI_API_KEY non impostata.")
        print("Esegui: export GEMINI_API_KEY='la-tua-chiave'  (Linux/Mac)")
        print("oppure: $env:GEMINI_API_KEY='la-tua-chiave'    (Windows PowerShell)")
        sys.exit(1)

    profilo_di_test = (
        "L'utente apprezza particolarmente concerti rock e indie, "
        "mostra scarso interesse per eventi di musica classica."
    )

    print("Chiamata a Gemini con Google Search Grounding in corso...\n")
    eventi = cerca_eventi(profilo_di_test)

    print(f"\n--- Trovati {len(eventi)} eventi ---\n")
    print(json.dumps(eventi, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
