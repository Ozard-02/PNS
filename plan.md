# Plan — Taglio costi: OpenRouter free + fetch diretto (no Tavily/Groq/Gemini a pagamento)

## Obiettivo
Mantenere il workflow PNS invariato (cron + Docker, 5 step in `app/main.py`),
eliminando ogni dipendenza da servizio a pagamento:
- LLM (profilo + interpretazione) → **OpenRouter** su modelli `:free` (una sola `OPENROUTER_API_KEY`, nessun billing).
- Ricerca web (Tavily) → **fetch HTTP diretto** senza API key (DuckDuckGo HTML + scraping leggero, solo `requests` + `beautifulsoup4`).

## Stato attuale (da verificare in `structure.md`)
- `app/profile_engine.py`: `_genera_con_groq` / `_genera_con_gemini` via `PROFILE_ENGINE`.
- `app/search_client.py`: Fase A `_cerca_con_tavily()` (Tavily API), Fase B `_interpreta_con_groq` / `_interpreta_con_gemini` via `INTERPRETER_ENGINE`.
- `app/config.py`: `GEMINI_API_KEY`, `GROQ_API_KEY`, `TAVILY_API_KEY`, `PROFILE_ENGINE`, `INTERPRETER_ENGINE`, `GEMINI_PROFILE_MODEL`, `GROQ_MODEL`, `TAVILY_MAX_RESULTS`.
- `requirements.txt`: `google-genai`, `groq`, `tavily-python` (+ google calendar, dotenv).
- `docker-compose.yml` + `env-template.txt`: passano le 3 API key.

## Proposta (KISS: riusa codice esistente, 1 file = 1 responsabilità)
1. **`app/config.py`** — aggiunge `OPENROUTER_API_KEY`, `OPENROUTER_MODEL` (default: `meta-llama/llama-3.3-70b-instruct:free`), `SEARCH_MAX_RESULTS` (riuso di `TAVILY_MAX_RESULTS` rinominato o alias). Rimuove (o depreca) `GEMINI_*/GROQ_*/TAVILY_*`.
2. **Nuovo `app/llm_client.py`** (unica responsabilità: chiamate LLM) — un solo `chiama_llm(prompt, max_tokens, temperature)` via `POST https://openrouter.ai/api/v1/chat/completions` con `requests` (OpenAI-compatible, niente SDK nuovo). Usato sia da `profile_engine.py` sia da `search_client.py`. Include timeout + gestione errori minimale (raise con messaggio, `main.py` già fa `sys.exit(1)`).
3. **`app/profile_engine.py`** — sostituisce `_genera_con_groq/_genera_con_gemini/_chiama_llm` con import da `llm_client`. Nessun cambio di prompt.
4. **`app/search_client.py`** — Fase A: sostituisce `_cerca_con_tavily()` con `_cerca_con_duckduckgo()`: `GET https://html.duckduckgo.com/html/?q=...` con User-Agent browser, parse link con `beautifulsoup4`, poi fetch testuale delle prime N pagine (stesso `requests`, troncamento a ~1500 char come oggi). Riusa `_build_queries()`, `_formatta_risultati_grezzi()`, `_limita_input()` invariati. Fase B: sostituisce `_interpreta_con_*` con `llm_client.chiama_llm`. Filtri data/dedup/merge invariati.
5. **`requirements.txt` (+ `uv.lock`)** — rimuove `google-genai`, `groq`, `tavily-python`; aggiunge `requests`, `beautifulsoup4` (pinned). Calendar/dotenv invariati.
6. **`docker-compose.yml` + `env-template.txt`** — sostituiscono le 3 key con `OPENROUTER_API_KEY` e `OPENROUTER_MODEL`; tolgono `TAVILY_MAX_RESULTS` → `SEARCH_MAX_RESULTS`.
7. **`structure.md`** — aggiorna tabella env + descrizione step 2/3 (OpenRouter + fetch diretto).
8. **`improvements.md`** — spunta/aggiunge voce "fallback provider" solo se deciso (vedi domande).

## Best practice (note)
- OpenRouter è già OpenAI-compatible: `requests.post` basta, nessuno SDK extra (KISS, meno dipendenze). Header `HTTP-Referer`/`X-Title` facoltativi.
- Modelli `:free` hanno limiti (~50 req/giorno, rate-limit e disponibilità variabile). PNS fa ~2 chiamate LLM/giorno (1 profilo + 1 interpretazione) → ampiamente dentro. Fissare `OPENROUTER_MODEL` via env così se un modello free sparisce si cambia senza codice. Best practice: prevedere 2-3 modelli in fallback ordinato (domanda Q2).
- DuckDuckGo HTML scraping è fragile (cambi layout, 429/403). Mitigazioni: User-Agent reale, `time.sleep(1)` tra query, timeout 15s, try/except per pagina (come oggi per Tavily). Alternativa senza key: `r.jina.ai/http://URL` per estrarre testo — da valutare solo se DDG blocca (non aggiungere ora, KISS).
- Sicurezza (AGENTS.md): key solo via env in `config.py`; validare JSON LLM come oggi (`_estrai_json` invariato); nessun `eval/exec`.

## Checklist
- [x] Q1–Q3 sotto risposte dall'utente (rimozione totale, modello singolo, rename env)
- [x] `app/llm_client.py` creato (singola funzione + timeout/errori)
- [x] `app/config.py` aggiornato (nuove env, rimosse vecchie)
- [x] `app/profile_engine.py` migrato a `llm_client`
- [x] `app/search_client.py` migrato (Fase A DDG + Fase B `llm_client`)
- [x] `requirements.txt` + `uv.lock` aggiornati e pinnati
- [x] `docker-compose.yml` + `env-template.txt` aggiornati
- [x] `structure.md` aggiornato (step 2/3, tabella env, layout con `llm_client.py`)
- [x] Verifica: `python -m compileall app/` + import test nel container (con nuove dipendenze) — build `docker compose up -d --build` riuscita
- [ ] Verifica: run manuale produce eventi / log puliti; `feedback_cli.py --review` ok (richiede `OPENROUTER_API_KEY` nel `.env`: `docker exec -it ai-event-tracker python /app/main.py`)

## Fase 2 — Query adattive (stato: da implementare)

Decisioni utente (2026-10-14): provenance in DB, file `/data/query_templates.txt`, auto-proposal nel daily run.

### Disegno
- `app/query_store.py` (nuovo): legge/scrive `/data/query_templates.txt` (una riga = un template, `#` commenti, placeholder ammessi `{location} {mese_anno} {oggi} {fine}`). Se manca, lo crea con i 3 default attuali. Valida righe (max 10, max 300 char, solo placeholder noti — sanitizza input esterno). `build_queries()` → coppie `(template, rendered)`.
- `app/search_client.py`: `_build_queries()` riusa `query_store`; ogni risultato grezzo è taggato con `template_origine` (il template, non la query renderizzata con date). Merge/dedup conservano l'origine del primo ritrovamento (copie di dict esistenti, nessun cambio).
- `app/db.py`: `eventi.query_origine TEXT DEFAULT NULL` (CREATE + migrazione `ALTER TABLE` protetta per DB esistenti); `insert_evento` la salva. Nuova tabella `query_proposals` (id, template, motivazione, azione `aggiungi|sostituisci`, indice_target, stato `pending|accepted|rejected`, created_at) + funzioni CRUD. `get_stats_per_query()`: per template, n_eventi / n_valutati / media voti utente.
- `app/query_engine.py` (nuovo): `genera_proposte_query(force=False)` — guard: skip se pending esistenti o <3 nuovi feedback dall'ultima proposta; altrimenti prompt con profilo + template numerati con statistiche + titoli piaciuti/non piaciuti → max 3 proposte JSON validate → salvate come `pending`. Mai applicate in automatico.
- `app/main.py`: Step 6 non-fatale (try/except con solo warning, non `sys.exit`) dopo Calendar.
- `app/feedback_cli.py`: `--queries` (template numerati + statistiche), `--propose [--force]`, `--proposals` (loop accetta/rifiuta/salta come `--review`; accept riscrive il file via `salva_template`).
- `app/config.py`: `QUERY_TEMPLATES_PATH` (default `/data/query_templates.txt`).
- Docs: `structure.md`, `README.md` (sezione TUI, layout, env).

### Fix applicati durante il debug (2026-10-14)
- `llm_client.py`: nuova eccezione `LLMResponseError` (sottoclasse di `ValueError`) per risposte senza contenuto; chiave mancante resta `ValueError` esplicito.
- `query_engine.py`: riuso `_estrai_json` da `search_client` (recupera JSON troncati) + `_normalizza_proposta` (accetta dialetti `query`/`index`) + retry 3x + nessun traceback (messaggio pulito, ritorna 0).
- Budget token alzati per modelli reasoning (nemotron-lightning brucia ~1700 token di ragionamento prima di rispondere): profilo 500→2500, interpretazione 2000→5000, proposte→4000. Prompt proposte con profilo troncato a 800 char.
- Default `OPENROUTER_MODEL` → `nvidia/nemotron-3-ultra-550b-a55b:free` (`llama-3.3-70b` non esiste più: 404). Lista modelli free verificata via `/api/v1/models` (14 modelli `:free`).
- Tutti i prompt ora impongono concisione: profilo (max 8-10 frasi brevi), motivazioni evento/proposte (una sola frase, niente fronzoli).
- Verdetto modello (15/10, prove live): `nemotron-3.5-lightning` NON usabile per prompt lunghi (12/12 vuoti sui chunk da ~8k char, pur rispondendo ai prompt brevi: brucia ~1700 token di reasoning e sui contesti lunghi torna null). `nemotron-3-ultra` risponde allo STESSO prompt al 1° tentativo. `.env` riportato su ultra. Resta flakiness residua (retry/prosa scartata) ma il design tollerante produce risultati parziali invece di zero.
- Verifica live 15/10: `test_search_locale.py` end-to-end OK — 15 grezzi → 2 eventi reali (date/luoghi validi, punteggi coerenti col profilo rock) con `template_origine` popolato (fix provenance confermato sul campo). Quota usata oggi ~28/50: da qui in poi solo verifiche offline salvo tuo via.
- Confronto modelli 15/10 (stesso prompt ~10k char, 2 tentativi ciascuno, `/tmp/opencode/test_models.py`): `nemotron-3-super-120b` 2/2 perfetto (JSON strict, schema+fonte, motivazioni ~55 char); `ultra` 1/2 (overload upstream); `gemma-4-31b` 0/2 (429 upstream, due giorni di fila). Default + `.env` su super-120b.
- Chunking Fase B (`search_client.py`, `CHUNK_SIZE=4`): prompt piccoli (~6k char) invece di uno da ~27k che i modelli free lasciano vuoto. Un chunk fallito non blocca gli altri. Verificato offline con mock (`/tmp/opencode/test_chunk.py`).
- BUG provenance corretto: `template_origine` non arrivava mai agli eventi interpretati (dict freschi dall'LLM) → colonna sempre NULL. Ora lo schema richiede `fonte_risultato` (indice 1-based nel chunk) e `cerca_eventi` lo mappa al template, con fallback None su indici invalidi. Le statistiche per query si popolano dal prossimo run riuscito.

### Checklist Fase 2
- [x] `app/query_store.py` creato (seed, validazione, render)
- [x] `app/db.py`: colonna `query_origine` + migrazione + tabella `query_proposals` + stats
- [x] `app/search_client.py`: tag origine sui risultati
- [x] `app/query_engine.py` creato (guard + prompt + validazione proposte)
- [x] `app/main.py`: Step 6 non-fatale
- [x] `app/feedback_cli.py`: `--queries` / `--propose` / `--proposals`
- [x] `app/config.py`: `QUERY_TEMPLATES_PATH`
- [x] Docs (`structure.md`, `README.md`)
- [x] Verifica: `compileall` + 10 test funzionali locali (`/tmp/opencode/test_fase2.py`, tutti OK) + `docker compose up -d --build` + import/test funzionali nel container + `--queries`/`--proposals` sul DB reale (seed `/data/query_templates.txt` creato)
- [x] Run manuale completo 15/10 (`docker exec ai-event-tracker python /app/main.py`): 15 grezzi → 6 eventi (4/4 chunk OK, 1 retry + 1 salvage) → 6 salvati in DB → 6 su Calendar → Step 6 bloccato dal guard (3 proposte pending). Durata ~5 min.

## Rischi aperti
- Quota OpenRouter free: 50 req/giorno condivise tra TUTTI gli step + usi manuali/debug (il run giornaliero ne usa ~2-3). A quota esaurita gli step falliscono con messaggio chiaro (`QuotaGiornalieraEsaurita`, reset a mezzanotte UTC) senza retry inutili. Non sprecare chiamate in debug: preferire test con guard/mock.
- Modello free OpenRouter non disponibile / rate-limit upstream → retry 3x in `llm_client` (null/429/5xx), poi errore. Mitigato da cambio modello via env (i modelli `:free` cambiano spesso: verificare su `/api/v1/models`).
- DuckDuckGo risponde 202 (challenge) alle query renderizzate oltre ~90 char → `_scarica_links_ddg` ritenta 1x poi scarta con hint; default e prompt impongono template brevi (<60 char + placeholder).
- Qualità interpretazione modelli free → più scarti dal filtro data o JSON malformato. Mitigato: prompt invariato + `_estrai_json` con recupero parziale già esistente.
- DDG blocca scraping → zero risultati grezzi → `cerca_eventi` ritorna `[]` (comportamento già gestito).
- Template con placeholder ignoti o >300 char vengono scartati con warning (file esterno = input non fidato).
