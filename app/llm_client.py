"""
Unica responsabilità: chiamate LLM via OpenRouter (modelli `:free`, nessun billing).

Usato sia da `profile_engine.py` (profilo utente) sia da `search_client.py`
(interpretazione risultati web). API OpenAI-compatible, basta `requests`.
"""
import time
from datetime import datetime, timezone

import requests

from config import (
    OPENROUTER_API_KEY,
    OPENROUTER_MODEL,
    LOCAL_LLM_URL,
    LOCAL_API_KEY,
    LOCAL_MODEL,
)

API_URL = "https://openrouter.ai/api/v1/chat/completions"
TIMEOUT_SECS = 60
LOCAL_TIMEOUT_SECS = 300
RETRY_SLEEP_SECS = 5


class LLMResponseError(ValueError):
    """Il provider ha risposto ma senza contenuto utilizzabile (es. content null dei modelli free)."""


class QuotaGiornalieraEsaurita(ValueError):
    """Quota giornaliera modelli free esaurita (HTTP 429 free-models-per-day)."""


def quota_reset_str(response) -> str:
    """Estrae l'orario di reset quota (UTC) dalla risposta 429, best-effort."""
    try:
        reset_ms = response.json()["error"]["metadata"]["headers"]["X-RateLimit-Reset"]
        reset = datetime.fromtimestamp(int(reset_ms) / 1000, tz=timezone.utc)
        return "alle " + reset.strftime("%H:%M UTC del %d/%m")
    except (KeyError, TypeError, ValueError):
        return "a mezzanotte UTC"


def _tentativo(url: str, api_key: str, model: str, prompt: str,
               max_tokens: int, temperature: float, timeout: int,
               extra_body: dict | None = None) -> str:
    body = {
        "model": model,
        "messages": [{"role": "user", "content": prompt}],
        "temperature": temperature,
        "max_tokens": max_tokens,
    }
    if extra_body:
        body.update(extra_body)
    risposta = requests.post(
        url,
        headers={"Authorization": f"Bearer {api_key}"},
        json=body,
        timeout=timeout,
    )
    risposta.raise_for_status()
    try:
        testo = risposta.json()["choices"][0]["message"]["content"]
    except (KeyError, IndexError, AttributeError) as e:
        raise LLMResponseError(f"Risposta inattesa da {model}: {e}")
    if not (testo or "").strip():
        raise LLMResponseError("contenuto vuoto")
    return testo.strip()


def _chiama_openrouter(prompt: str, max_tokens: int, temperature: float,
                       tentativi: int = 3) -> str:
    if not OPENROUTER_API_KEY:
        raise ValueError("OPENROUTER_API_KEY non impostata.")

    ultimo_errore = None
    for tentativo in range(1, tentativi + 1):
        try:
            return _tentativo(API_URL, OPENROUTER_API_KEY, OPENROUTER_MODEL,
                              prompt, max_tokens, temperature, TIMEOUT_SECS)
        except LLMResponseError as e:
            ultimo_errore = e
            print(f"[llm_client] Tentativo {tentativo}/{tentativi} senza contenuto ({e}).")
        except requests.HTTPError as e:
            status = e.response.status_code if e.response is not None else None
            if status == 429:
                if e.response is not None and "free-models-per-day" in e.response.text:
                    raise QuotaGiornalieraEsaurita(
                        "Quota giornaliera modelli free esaurita (50/giorno). "
                        f"Reset {quota_reset_str(e.response)}. "
                        "Riprova dopo il reset o aggiungi crediti su openrouter.ai."
                    )
                ultimo_errore = e  # 429 upstream: riprova tra poco
                print(f"[llm_client] HTTP 429 upstream (tentativo {tentativo}/{tentativi}), riprovo...")
            elif status in (500, 502, 503):
                ultimo_errore = e
                print(f"[llm_client] HTTP {status} (tentativo {tentativo}/{tentativi}), riprovo...")
            else:
                raise
        if tentativo < tentativi:
            time.sleep(RETRY_SLEEP_SECS)
    raise ultimo_errore


def chiama_llm(prompt: str, max_tokens: int = 2000, temperature: float = 0.2,
               tentativi: int = 3) -> str:
    """Invia un prompt al LLM e restituisce il testo della risposta.

    Se LOCAL_LLM_URL è configurato, prova prima l'istanza locale (senza quota,
    con thinking disabilitato per Qwen3) e ripiega su OpenRouter solo in errore.
    Altrimenti va diretto su OpenRouter con retry su vuoto/429/5xx.
    """
    if LOCAL_LLM_URL:
        if not LOCAL_API_KEY:
            print("[llm_client] LOCAL_LLM_URL senza LOCAL_API_KEY: uso OpenRouter.")
        else:
            try:
                return _tentativo(LOCAL_LLM_URL.rstrip("/") + "/chat/completions",
                                  LOCAL_API_KEY, LOCAL_MODEL,
                                  prompt, max_tokens, temperature,
                                  LOCAL_TIMEOUT_SECS,
                                  extra_body={"enable_thinking": False})
            except Exception as e:
                print(f"[llm_client] Istanza locale non disponibile ({e}): fallback OpenRouter.")
    return _chiama_openrouter(prompt, max_tokens, temperature, tentativi)
