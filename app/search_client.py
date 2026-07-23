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
import difflib
import json
import re
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

MAX_INPUT_CHARS = 25000


def _limita_input(testo: str) -> str:
    if len(testo) <= MAX_INPUT_CHARS:
        return testo
    lines = testo.split("\n")
    troncato = []
    lunghezza = 0
    for line in lines:
        lunghezza += len(line) + 1
        if lunghezza > MAX_INPUT_CHARS:
            break
        troncato.append(line)
    n_tagliati = lines.count("--- Risultato") - troncato.count("--- Risultato")
    if n_tagliati > 0:
        print(f"[search_client] Input troncato a ~{MAX_INPUT_CHARS} caratteri: scartati {n_tagliati} risultati per rispettare il limite TPM di Groq.")
    return "\n".join(troncato)


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


def _build_queries() -> list[str]:
    oggi_dt = datetime.now()
    fine_dt = oggi_dt + timedelta(days=SEARCH_RADIUS_DAYS)
    oggi = oggi_dt.strftime("%Y-%m-%d")
    fine = fine_dt.strftime("%Y-%m-%d")
    mese_anno = oggi_dt.strftime('%B %Y')
    return [
        f"concerti spettacoli musical teatro {LOCATION} {mese_anno} dal {oggi} al {fine}",
        f"eventi underground indie alternativi nicchia piccoli locali {LOCATION} {mese_anno}",
        f"feste sagre mercatini mostre gratuiti ingresso libero {LOCATION} {mese_anno}",
    ]


def _cerca_con_tavily() -> list[dict]:
    """Fase A: interroga Tavily con più query, aggrega e deduplica per URL."""
    client = TavilyClient(api_key=TAVILY_API_KEY)
    visti = set()
    risultati_totali = []

    for query in _build_queries():
        try:
            risposta = client.search(
                query=query,
                max_results=TAVILY_MAX_RESULTS,
                search_depth="advanced",
                include_answer=False,
            )
            for r in risposta.get("results", []):
                url = r.get("url", "")
                if url not in visti:
                    visti.add(url)
                    risultati_totali.append({
                        "titolo_pagina": r.get("title", ""),
                        "url": url,
                        "contenuto": r.get("content", ""),
                    })
        except Exception as e:
            print(f"[search_client] Errore nella query '{query[:50]}...': {e}")
            continue

    return risultati_totali


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

    return f"""Sei un assistente che estrae informazioni su eventi pubblici da risultati di
ricerca web grezzi e li valuta in base al profilo di un utente.

DATA DI OGGI: {oggi}
INTERVALLO VALIDO: SOLO eventi con data compresa tra {oggi} e {fine} (inclusi).

REGOLA FONDAMENTALE SULLE DATE:
- Scarta OGNI evento la cui data è precedente a {oggi} (evento già passato) o successiva a {fine}.
- Le pagine web possono contenere date di edizioni passate, calendari generici o eventi
  di mesi diversi: verifica sempre l'anno e il giorno esatto prima di includere un evento.
- Se una pagina contiene più date, identifica quella riferita allo specifico evento.
- In caso di dubbio sulla data, scarta l'evento.

Profilo storico dell'utente (usalo per calcolare il punteggio di gradimento E per
preferire eventi che corrispondono ai suoi gusti descritti):
{profilo_utente}

Risultati grezzi della ricerca web:
{risultati_grezzi}

Analizza questi risultati ed estrai SOLO eventi pubblici reali con data e luogo
chiaramente identificabili e compresi nell'intervallo valido sopra indicato.

Sono considerati eventi validi, ad esempio:
- concerti (grandi e piccoli);
- spettacoli teatrali e musical;
- cabaret e comedy;
- festival, sagre e fiere;
- mostre ed eventi culturali;
- eventi enogastronomici;
- visite guidate, laboratori e attività esperienziali;
- manifestazioni aperte al pubblico;
- jam session, dj set, serate in locali;
- reading, presentazioni, incontri;
- eventi di quartiere, mercatini, ingresso libero.

VARIETÀ E NICCHIA:
- Cerca di includere una MISCELA di eventi: grandi produzioni MA ANCHE eventi
  underground, indipendenti, di nicchia, in piccoli locali, a basso costo o gratuiti.
- Non limitarti ai soli eventi mainstream: prediligi quelli che meglio
  corrispondono al profilo utente sopra descritto.
- Se il profilo utente accenna a preferenze per locali piccoli, atmosfere informali,
  generi di nicchia, musica indipendente, eventi non commerciali o sottocultura,
  DAI PRIORITÀ a quel tipo di eventi.

Procedura obbligatoria per ogni possibile evento:
1. Individua un possibile evento.
2. Verifica che siano presenti una data completa (giorno, mese e anno) e un luogo chiaramente identificabile.
3. Verifica che la data sia compresa tra {oggi} e {fine}.
4. Se manca uno qualsiasi dei requisiti precedenti, scarta l'evento.
5. Se più risultati descrivono lo stesso evento, mantieni una sola occorrenza scegliendo quella con le informazioni più complete.
6. Solo dopo assegna un punteggio di gradimento da 1 a 10 basandoti sul profilo utente.

Non inventare informazioni. Se data, luogo o tipologia dell'evento non sono chiaramente presenti nei risultati, scarta l'evento.

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

    try:
        return json.loads(testo)
    except json.JSONDecodeError:
        # Fallback: la risposta potrebbe essere troncata (max_tokens raggiunto).
        # Prova a recuperare l'ultimo oggetto completo dell'array.
        ultimo_oggetto_chiuso = testo.rfind("},")
        if ultimo_oggetto_chiuso != -1:
            testo_recuperato = testo[:ultimo_oggetto_chiuso + 1] + "]"
            try:
                eventi_parziali = json.loads(testo_recuperato)
                print(f"[search_client] JSON troncato: recuperati {len(eventi_parziali)} eventi completi su risposta incompleta.")
                return eventi_parziali
            except json.JSONDecodeError:
                pass
        raise


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


def _normalizza_testo(testo: str) -> str:
    """Normalizza un testo per il matching: lowercase, strip, rimuovi punteggiatura."""
    testo = (testo or "").strip().lower()
    testo = re.sub(r"[^\w\s]", "", testo)
    testo = re.sub(r"\s+", " ", testo).strip()
    return testo


def _titoli_simili(t1: str, t2: str, soglia: float = 0.95) -> bool:
    """Confronta due titoli usando fuzzy matching."""
    return difflib.SequenceMatcher(None, t1, t2).ratio() >= soglia


def _date_sono_consecutive(date_list: list[str]) -> bool:
    """Verifica che le date formino un blocco consecutivo (nessun gap > 1 giorno)."""
    if len(date_list) <= 1:
        return True
    parsed = sorted(datetime.strptime(d, "%Y-%m-%d").date() for d in date_list)
    for i in range(len(parsed) - 1):
        if (parsed[i + 1] - parsed[i]).days != 1:
            return False
    return True


def _merge_multi_date_events(eventi: list[dict]) -> list[dict]:
    """
    Raggruppa eventi con stesso titolo (fuzzy) e luogo in un unico evento multi-data
    se le date sono consecutive. Se non consecutive, li numera (1/N, 2/N, ...).
    """
    if not eventi:
        return []

    # Costruisci gruppi per similarità
    assegnati = [False] * len(eventi)
    gruppi = []

    for i, ev in enumerate(eventi):
        if assegnati[i]:
            continue
        gruppo = [i]
        assegnati[i] = True
        norm_i = (
            _normalizza_testo(ev.get("titolo")),
            _normalizza_testo(ev.get("luogo")),
        )
        for j in range(i + 1, len(eventi)):
            if assegnati[j]:
                continue
            ev_j = eventi[j]
            norm_j = (
                _normalizza_testo(ev_j.get("titolo")),
                _normalizza_testo(ev_j.get("luogo")),
            )
            if (
                _titoli_simili(norm_i[0], norm_j[0])
                and norm_i[1] == norm_j[1]
            ):
                gruppo.append(j)
                assegnati[j] = True
        gruppi.append(gruppo)

    risultati = []
    for gruppo in gruppi:
        if len(gruppo) == 1:
            risultati.append(eventi[gruppo[0]])
            continue

        eventi_gruppo = [eventi[i] for i in gruppo]
        # Raccogli tutte le date valide
        date_valide = sorted(
            set(e["data"] for e in eventi_gruppo if e.get("data"))
        )

        if len(date_valide) <= 1:
            risultati.extend(eventi_gruppo)
            continue

        if _date_sono_consecutive(date_valide):
            # Merge: singolo evento multi-data
            base = dict(eventi_gruppo[0])
            base["data"] = date_valide[0]
            base["data_fine"] = date_valide[-1]
            # Unisci link_info e motivazione dal primo più completo
            migliori = sorted(eventi_gruppo, key=lambda e: len(e.get("motivazione_punteggio", "") or ""), reverse=True)
            base["link_info"] = migliori[0].get("link_info", base.get("link_info"))
            base["motivazione_punteggio"] = migliori[0].get("motivazione_punteggio", base.get("motivazione_punteggio"))
            # Media dei punteggi
            punteggi = [e["punteggio_predetto"] for e in eventi_gruppo if e.get("punteggio_predetto") is not None]
            if punteggi:
                base["punteggio_predetto"] = round(sum(punteggi) / len(punteggi), 1)
            risultati.append(base)
        else:
            # Non consecutive: numera gli eventi
            totale = len(eventi_gruppo)
            for idx, e in enumerate(eventi_gruppo, 1):
                e = dict(e)
                e["titolo"] = f"{e['titolo']} ({idx}/{totale})"
                risultati.append(e)

    return risultati


def _completezza_evento(e: dict) -> int:
    """Quanti campi non vuoti ha un evento (più alto = più informativo)."""
    return sum(1 for v in e.values() if v and str(v).strip())


def _date_sovrapposte(a: dict, b: dict) -> bool:
    """Due eventi hanno date sovrapposte? Gestisce anche multi-day."""
    a_inizio = a.get("data", "")
    a_fine = a.get("data_fine", "") or a_inizio
    b_inizio = b.get("data", "")
    b_fine = b.get("data_fine", "") or b_inizio
    if not a_inizio or not b_inizio:
        return False
    return a_inizio <= b_fine and b_inizio <= a_fine


def _deduplica_eventi(eventi: list[dict]) -> list[dict]:
    """
    Post-dedup: se due eventi hanno date sovrapposte, titoli e luoghi simili,
    sono lo stesso evento con wording diverso. Tiene il più completo.
    """
    if len(eventi) < 2:
        return eventi

    da_tenere = []
    for ev in eventi:
        norm_titolo = _normalizza_testo(ev.get("titolo", ""))
        norm_luogo = _normalizza_testo(ev.get("luogo", ""))
        completo_ev = _completezza_evento(ev)

        duplicato = False
        for i, tenuto in enumerate(da_tenere):
            norm_t = _normalizza_testo(tenuto.get("titolo", ""))
            if not _titoli_simili(norm_titolo, norm_t, 0.8):
                continue

            norm_l = _normalizza_testo(tenuto.get("luogo", ""))
            if not _date_sovrapposte(ev, tenuto) and not _titoli_simili(norm_luogo, norm_l, 0.7):
                continue

            duplicato = True
            if completo_ev > _completezza_evento(tenuto):
                da_tenere[i] = ev
            break

        if not duplicato:
            da_tenere.append(ev)

    return da_tenere


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
    risultati_formattati = _limita_input(_formatta_risultati_grezzi(risultati_grezzi))
    prompt = _build_prompt_interpretazione(profilo_utente, risultati_formattati)

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

    eventi_merged = _merge_multi_date_events(eventi_filtrati)
    if len(eventi_merged) != len(eventi_filtrati):
        pl = "e" if len(eventi_merged) == 1 else "i"
        print(
            f"[search_client] Uniti {len(eventi_filtrati) - len(eventi_merged)} eventi "
            f"multi-data in {len(eventi_merged)} event{pl} finali."
        )

    eventi_deduplicati = _deduplica_eventi(eventi_merged)
    if len(eventi_deduplicati) != len(eventi_merged):
        print(
            f"[search_client] Deduplicati {len(eventi_merged) - len(eventi_deduplicati)} eventi "
            f"con titoli simili."
        )

    return eventi_deduplicati
