"""
Step 3 del workflow: ricerca eventi/concerti tramite Gemini con Google Search Grounding.

Questa è l'UNICA parte del sistema che ha accesso a internet (tramite il tool
di Google Search integrato in Gemini).
"""
import json
from datetime import datetime, timedelta

from google import genai
from google.genai import types

from config import GEMINI_API_KEY, GEMINI_SEARCH_MODEL, LOCATION, SEARCH_RADIUS_DAYS

RESPONSE_SCHEMA_DESCRIPTION = """
Rispondi ESCLUSIVAMENTE con un array JSON valido (nessun testo prima o dopo, nessun
blocco markdown ```), con questa struttura per ogni evento trovato:

[
  {
    "titolo": "string",
    "data": "string formato YYYY-MM-DD",
    "luogo": "string - indirizzo o nome locale",
    "link_info": "string - URL per biglietti o info",
    "genere_categoria": "string - es. Rock, Teatro, Jazz, ecc.",
    "punteggio_predetto": "numero float da 1.0 a 10.0",
    "motivazione_punteggio": "string - breve frase che spiega il voto basato sul profilo utente"
  }
]

Se non trovi eventi, rispondi con un array vuoto: []
"""


def _build_prompt(profilo_utente: str) -> str:
    oggi = datetime.now().strftime("%Y-%m-%d")
    fine = (datetime.now() + timedelta(days=SEARCH_RADIUS_DAYS)).strftime("%Y-%m-%d")

    return f"""Sei un assistente personale esperto di eventi musicali e culturali.

Cerca concerti, spettacoli ed eventi a {LOCATION} nel periodo dal {oggi} al {fine}.

Profilo storico dell'utente (usa queste informazioni per calcolare il punteggio di
gradimento di ogni evento trovato):
{profilo_utente}

Per ogni evento trovato, calcola un punteggio di gradimento da 1 a 10 basandoti sul
profilo utente sopra riportato.

{RESPONSE_SCHEMA_DESCRIPTION}
"""


def _estrai_json(testo: str) -> list[dict]:
    """Ripulisce la risposta del modello da eventuali fence markdown e la parsea come JSON."""
    testo = testo.strip()
    if testo.startswith("```"):
        # Rimuove ```json ... ``` o ``` ... ```
        testo = testo.split("```")[1]
        if testo.startswith("json"):
            testo = testo[4:]
    testo = testo.strip()
    return json.loads(testo)


def cerca_eventi(profilo_utente: str) -> list[dict]:
    """Chiama Gemini con Google Search Grounding attivo e ritorna la lista di eventi trovati."""
    client = genai.Client(api_key=GEMINI_API_KEY)

    grounding_tool = types.Tool(google_search=types.GoogleSearch())

    prompt = _build_prompt(profilo_utente)

    response = client.models.generate_content(
        model=GEMINI_SEARCH_MODEL,
        contents=prompt,
        config=types.GenerateContentConfig(
            tools=[grounding_tool],
        ),
    )

    try:
        eventi = _estrai_json(response.text)
    except (json.JSONDecodeError, IndexError, AttributeError) as e:
        print(f"[search_client] Errore nel parsing della risposta di Gemini: {e}")
        print(f"[search_client] Risposta grezza:\n{response.text}")
        return []

    if not isinstance(eventi, list):
        print("[search_client] La risposta non è una lista JSON come atteso.")
        return []

    return eventi
