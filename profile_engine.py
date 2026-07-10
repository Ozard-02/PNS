"""
Step 2 del workflow: "motore offline" (nessun accesso a internet/tool di ricerca).

Compito:
1. Leggere lo storico dei feedback (punteggio_utente vs punteggio_gemini) dal DB.
2. Produrre un "Profilo Utente" testuale aggiornato (gusti, generi preferiti/scartati).
3. Restituire il blocco di testo da iniettare nel prompt di ricerca per Gemini.

Due backend intercambiabili tramite config.PROFILE_ENGINE:
- "gemini": stessa API Gemini, ma SENZA il tool di search grounding (chiamata pura testo->testo)
- "groq": Groq API (free tier, modelli Llama/Mistral) - completamente separata da Google

Entrambi i backend NON hanno accesso a internet in questa fase: lavorano solo sui dati
che gli passiamo esplicitamente (i feedback letti da SQLite).
"""
from db import get_feedback_recente, salva_profilo, get_ultimo_profilo
from config import PROFILE_ENGINE

SYSTEM_PROMPT = """Sei un analista di preferenze musicali ed eventi. Il tuo compito è leggere
lo storico dei feedback di un utente (punteggio previsto dall'AI vs punteggio reale dato
dall'utente) e produrre un breve "Profilo Utente" aggiornato da usare per migliorare le
previsioni future.

Regole:
- Individua generi/artisti/tipi di evento dove l'utente ha corretto il punteggio verso l'ALTO
  (piace più di quanto previsto) e generi dove lo ha corretto verso il BASSO (piace meno).
- Sii sintetico: massimo 5-6 frasi, in formato elenco puntato.
- Scrivi in italiano, in terza persona (es. "L'utente apprezza particolarmente...").
- Se non ci sono abbastanza dati (meno di 3 feedback), restituisci un profilo neutro generico.
- NON inventare dati che non sono presenti nello storico fornito.
- Rispondi SOLO con il profilo, senza preamboli o commenti aggiuntivi.
"""


def _format_feedback_per_prompt(feedback: list[dict]) -> str:
    if not feedback:
        return "Nessun dato storico disponibile."
    righe = []
    for f in feedback:
        righe.append(
            f"- Evento: {f['titolo']} | Genere: {f['genere_categoria']} | "
            f"Punteggio AI: {f['punteggio_gemini']} | Punteggio reale utente: {f['punteggio_utente']}"
        )
    return "\n".join(righe)


def _genera_con_gemini(feedback_testo: str) -> str:
    from google import genai
    from config import GEMINI_API_KEY, GEMINI_PROFILE_MODEL

    client = genai.Client(api_key=GEMINI_API_KEY)
    # IMPORTANTE: nessun tool di search qui, chiamata puramente testuale
    response = client.models.generate_content(
        model=GEMINI_PROFILE_MODEL,
        contents=f"{SYSTEM_PROMPT}\n\nStorico feedback:\n{feedback_testo}",
    )
    return response.text.strip()


def _genera_con_groq(feedback_testo: str) -> str:
    from groq import Groq
    from config import GROQ_API_KEY, GROQ_MODEL

    client = Groq(api_key=GROQ_API_KEY)
    completion = client.chat.completions.create(
        model=GROQ_MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Storico feedback:\n{feedback_testo}"},
        ],
        temperature=0.3,
        max_tokens=500,
    )
    return completion.choices[0].message.content.strip()


def genera_profilo_utente() -> str:
    """Punto di ingresso principale: legge il DB e produce il profilo utente aggiornato."""
    feedback = get_feedback_recente(limit=50)
    feedback_testo = _format_feedback_per_prompt(feedback)

    if PROFILE_ENGINE == "groq":
        profilo = _genera_con_groq(feedback_testo)
    elif PROFILE_ENGINE == "gemini":
        profilo = _genera_con_gemini(feedback_testo)
    else:
        raise ValueError(f"PROFILE_ENGINE non valido: {PROFILE_ENGINE!r} (usa 'gemini' o 'groq')")

    salva_profilo(profilo)
    return profilo


def get_profilo_corrente() -> str:
    """Ritorna l'ultimo profilo generato, o un profilo neutro se non esiste ancora."""
    profilo = get_ultimo_profilo()
    if profilo:
        return profilo
    return "Nessun profilo storico disponibile ancora: prima esecuzione del sistema."
