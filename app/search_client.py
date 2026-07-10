"""
Step 3 del workflow: ricerca eventi/concerti.

Architettura a due fasi (sostituisce il precedente approccio con Gemini Search Grounding,
che richiede un account Google Cloud con billing collegato anche solo per la quota gratuita):

  Fase A - RICERCA (online): Tavily API cerca sul web e ritorna risultati puliti
            (titolo pagina, snippet, URL). Free tier: 1000 query/mese, nessuna carta richiesta.

  Fase B - INTERPRETAZIONE (online ma nessun tool di ricerca attivo): un LLM (Gemini o Groq,
            selezionabile con INTERPRETER_ENGINE) legge i risultati grezzi di Tavily e li
            trasforma nel JSON strutturato richiesto dal resto del sistema.

Questo approccio funziona interamente su free tier "puri", senza dover collegare billing
a nessun account.
"""
import json
from datetime import datetime, timedelta

from tavily import TavilyClient

from config import (
    TAVILY_API_KEY,
    TAVILY_MAX_RESULTS,
    LOCATION,
    SEARCH_RADIUS_DAYS,
    INTERPRETER_ENGINE,
    GEMINI_API_KEY,
    GEMINI_PROFILE_MODEL,
    GROQ_API_KEY,
    GROQ_MODEL,
)

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

Se dai risultati grezzi non emerge nessun evento reale con data e luogo, rispondi con
un array vuoto: []. NON inventare eventi che non sono chiaramente menzionati nei risultati.
"""


def _build_query() -> str:
    oggi_dt = datetime.now()
    fine_dt = oggi_dt + timedelta(days=SEARCH_RADIUS_DAYS)
    oggi = oggi_dt.strftime("%Y-%m-%d")
    fine = fine_dt.strftime("%Y-%m-%d")
    return (
        f"concerti eventi spettacoli {LOCATION} "
        f"dal {oggi} al {fine} ({oggi_dt.strftime('%B %Y')})"
    )


def _cerca_con_tavily() -> list[dict]:
    """Fase A: interroga Tavily e ritorna i risultati grezzi (titolo, url, snippet)."""
    client = TavilyClient(api_key=TAVILY_API_KEY)
    query = _build_query()

    risposta = client.search(
        query=query,
        max_results=TAVILY_MAX_RESULTS,
        search_depth="advanced",
        include_answer=False,
    )

    risultati = risposta.get("results", [])
    return [
        {
            "titolo_pagina": r.get("title", ""),
            "url": r.get("url", ""),
            "contenuto": r.get("content", ""),
        }
        for r in risultati
    ]


def _formatta_risultati_grezzi(risultati: list[dict]) -> str:
    if not risultati:
        return "Nessun risultato trovato dalla ricerca web."
    blocchi = []
    for i, r in enumerate(risultati, 1):
        blocchi.append(
            f"--- Risultato {i} ---\n"
            f"Titolo pagina: {r['titolo_pagina']}\n"
            f"URL: {r['url']}\n"
            f"Contenuto: {r['contenuto'][:1500]}"
        )
    return "\n\n".join(blocchi)


def _build_prompt_interpretazione(profilo_utente: str, risultati_grezzi: str) -> str:
    oggi = datetime.now().strftime("%Y-%m-%d")
    fine = (datetime.now() + timedelta(days=SEARCH_RADIUS_DAYS)).strftime("%Y-%m-%d")

    return f"""Sei un assistente che estrae informazioni su eventi/concerti da risultati di
ricerca web grezzi e li valuta in base al profilo di un utente.

DATA DI OGGI: {oggi}
INTERVALLO VALIDO: SOLO eventi con data compresa tra {oggi} e {fine} (inclusi).

REGOLA FONDAMENTALE SULLE DATE:
- Scarta OGNI evento la cui data è precedente a {oggi} (evento già passato) o successiva a {fine}.
- Le pagine web possono contenere date di edizioni passate, calendari generici o eventi
  di mesi diversi: verifica sempre l'anno e il giorno esatto prima di includere un evento.
- Se un risultato non riporta una data chiara e verificabile nell'intervallo valido, NON
  includerlo, anche se sembra rilevante.
- In caso di dubbio sulla data, escludi l'evento piuttosto che includerlo con una data incerta.

Profilo storico dell'utente (usalo per calcolare il punteggio di gradimento):
{profilo_utente}

Risultati grezzi della ricerca web:
{risultati_grezzi}

Analizza questi risultati ed estrai SOLO gli eventi reali (concerti, spettacoli, eventi
culturali) con data e luogo chiaramente identificabili E compresi nell'intervallo valido
sopra indicato. Per ognuno calcola un punteggio di gradimento da 1 a 10 basandoti sul
profilo utente.

{RESPONSE_SCHEMA_DESCRIPTION}
"""


def _estrai_json(testo: str) -> list[dict]:
    """Ripulisce la risposta del modello da eventuali fence markdown e la parsea come JSON."""
    testo = testo.strip()
    if testo.startswith("```"):
        testo = testo.split("```")[1]
        if testo.startswith("json"):
            testo = testo[4:]
    testo = testo.strip()
    return json.loads(testo)


def _interpreta_con_gemini(prompt: str) -> str:
    from google import genai

    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model=GEMINI_PROFILE_MODEL,
        contents=prompt,
    )
    return response.text.strip()


def _interpreta_con_groq(prompt: str) -> str:
    from groq import Groq

    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.2,
        max_tokens=2000,
    )
    return completion.choices[0].message.content.strip()


def _filtra_per_data_valida(eventi: list[dict]) -> list[dict]:
    """
    Filtro di sicurezza lato codice: scarta qualunque evento con data mancante, non
    parsabile, o fuori dall'intervallo [oggi, oggi+SEARCH_RADIUS_DAYS], indipendentemente
    da cosa ha deciso il modello. Così un errore del LLM sulle date non si propaga.
    """
    oggi = datetime.now().date()
    fine = (datetime.now() + timedelta(days=SEARCH_RADIUS_DAYS)).date()

    eventi_validi = []
    for evento in eventi:
        data_str = evento.get("data", "")
        try:
            data_evento = datetime.strptime(data_str, "%Y-%m-%d").date()
        except (ValueError, TypeError):
            print(f"[search_client] Scartato '{evento.get('titolo')}': data non valida ({data_str!r})")
            continue

        if data_evento < oggi or data_evento > fine:
            print(
                f"[search_client] Scartato '{evento.get('titolo')}': data {data_evento} "
                f"fuori intervallo [{oggi}, {fine}]"
            )
            continue

        eventi_validi.append(evento)

    return eventi_validi


def cerca_eventi(profilo_utente: str) -> list[dict]:
    """
    Punto di ingresso principale: esegue la ricerca web (Tavily) e poi l'interpretazione
    (Gemini o Groq) per produrre la lista di eventi strutturati.
    """
    # Fase A: ricerca web
    risultati_grezzi = _cerca_con_tavily()
    print(f"[search_client] Tavily ha restituito {len(risultati_grezzi)} risultati grezzi.")

    if not risultati_grezzi:
        return []

    # Fase B: interpretazione e strutturazione JSON
    prompt = _build_prompt_interpretazione(
        profilo_utente, _formatta_risultati_grezzi(risultati_grezzi)
    )

    if INTERPRETER_ENGINE == "groq":
        testo_risposta = _interpreta_con_groq(prompt)
    elif INTERPRETER_ENGINE == "gemini":
        testo_risposta = _interpreta_con_gemini(prompt)
    else:
        raise ValueError(
            f"INTERPRETER_ENGINE non valido: {INTERPRETER_ENGINE!r} (usa 'gemini' o 'groq')"
        )

    try:
        eventi = _estrai_json(testo_risposta)
    except (json.JSONDecodeError, IndexError) as e:
        print(f"[search_client] Errore nel parsing della risposta: {e}")
        print(f"[search_client] Risposta grezza:\n{testo_risposta}")
        return []

    if not isinstance(eventi, list):
        print("[search_client] La risposta non è una lista JSON come atteso.")
        return []

    eventi_filtrati = _filtra_per_data_valida(eventi)
    print(
        f"[search_client] {len(eventi_filtrati)}/{len(eventi)} eventi passano "
        f"il filtro data (scartati quelli fuori range o con data non valida)."
    )
    return eventi_filtrati
