# AI Event & Concert Tracker

Sistema automatico che ogni giorno cerca eventi/concerti vicino a te, li valuta in base
ai tuoi gusti (imparati dai tuoi feedback) e li inserisce su Google Calendar.

## Architettura

```
                    ┌─────────────────────────────────┐
                    │  STEP 2 - "Offline" (no internet)│
   SQLite  ───────► │  Groq API oppure Gemini no-search│ ───► Profilo Utente
  (feedback)         └─────────────────────────────────┘         (testo)
                                                                     │
                                                                     ▼
                    ┌─────────────────────────────────┐
                    │  STEP 3 - Online                 │
                    │  Gemini + Google Search Grounding │ ───► Lista eventi JSON
                    └─────────────────────────────────┘
                                                                     │
                                                                     ▼
                                                          SQLite (salva, evita duplicati)
                                                                     │
                                                                     ▼
                                                          Google Calendar (crea eventi)
```

Il modulo dello **Step 2** (`profile_engine.py`) è intercambiabile tramite la variabile
`PROFILE_ENGINE` nel file `.env`:
- `groq` → usa Groq API (free tier, modelli Llama/Mistral) — API separata da Google
- `gemini` → usa Gemini stesso ma con una seconda chiamata SENZA il tool di search

Entrambe le opzioni in questo step non hanno accesso a internet: lavorano solo sui dati
di feedback che leggono dal database SQLite.

## Setup

### 1. Chiavi API

**Gemini** (ricerca eventi): https://aistudio.google.com/apikey → crea una chiave gratuita.

**Groq** (opzionale, se scegli `PROFILE_ENGINE=groq`): https://console.groq.com/keys →
crea una chiave gratuita.

### 2. Google Calendar — credenziali OAuth2

1. Vai su https://console.cloud.google.com/ → crea un progetto (o usane uno esistente)
2. Abilita la **Google Calendar API**
3. Vai su "Credenziali" → "Crea credenziali" → "ID client OAuth" → tipo "App desktop"
4. Scarica il file JSON e rinominalo `credentials.json`
5. Mettilo nella cartella `./data/` (verrà montata nel container)

### 3. Primo avvio — autenticazione Calendar (una tantum)

L'autenticazione OAuth richiede un browser la prima volta. Il modo più semplice è
eseguirla **fuori da Docker**, in locale, una volta sola, per generare `token.json`:

```bash
cd app
pip install -r ../requirements.txt
python -c "from calendar_client import _get_credentials; _get_credentials()"
```

Si aprirà il browser, farai login con l'account Google del calendario di destinazione,
e verrà creato `token.json`. Copia sia `credentials.json` che `token.json` nella
cartella `./data/` prima di avviare il container Docker (che non ha un browser).

### 4. Configurazione

```bash
cp .env.example .env
nano .env   # inserisci le tue chiavi API
```

### 5. Build e avvio

```bash
docker compose up -d --build
```

Il container resta sempre attivo (`cron -f`) ed esegue `main.py` ogni giorno alle 07:00
(fuso orario Europe/Rome, configurabile nel Dockerfile).

### 6. Log

```bash
docker logs -f ai-event-tracker
```

### 7. Test manuale (senza aspettare il cron)

```bash
docker exec -it ai-event-tracker python /app/main.py
```

## Feedback loop — correggere i punteggi

Per insegnare al sistema i tuoi gusti reali, correggi il punteggio di un evento già
inserito:

```bash
# Vedi gli ultimi eventi con il loro ID
docker exec -it ai-event-tracker python /app/feedback_cli.py --list

# Correggi il punteggio dell'evento con id=12 a 8.5/10
docker exec -it ai-event-tracker python /app/feedback_cli.py --set 12 8.5
```

Il giorno successivo, lo Step 2 leggerà questo feedback e aggiornerà il profilo utente
di conseguenza, rendendo le previsioni future più accurate.

## Struttura file

```
event-tracker/
├── app/
│   ├── config.py          # configurazione centralizzata (env vars)
│   ├── db.py               # SQLite: schema e funzioni CRUD
│   ├── profile_engine.py   # Step 2: profilo utente (Groq o Gemini no-search)
│   ├── search_client.py    # Step 3: ricerca eventi (Gemini + Google Search)
│   ├── calendar_client.py  # Step 5: integrazione Google Calendar
│   ├── feedback_cli.py     # utility CLI per registrare i feedback
│   └── main.py             # orchestratore, eseguito dal cron
├── Dockerfile
├── docker-compose.yml
├── crontab
├── requirements.txt
└── .env.example
```

## Note sui costi/limiti free tier

- **Gemini 2.5 Flash**: free tier con limiti di richieste al giorno — verifica i limiti
  aggiornati su https://ai.google.dev/pricing (il Search Grounding ha una quota gratuita
  separata più bassa delle richieste normali)
- **Groq**: free tier generoso per richieste al minuto/giorno — verifica su
  https://console.groq.com/docs/rate-limits
- **Google Calendar API**: gratuita entro quote molto ampie per uso personale
