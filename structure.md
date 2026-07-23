# PNS — AI Event & Concert Tracker

## Overview

Automated pipeline that:
1. Reads historical user feedback from SQLite → generates an updated user profile (offline LLM)
2. Searches the web for events/concerts using Tavily
3. Interprets raw search results into structured JSON via a second LLM
4. Stores new events in SQLite (dedup by title + date + venue)
5. Syncs new events to Google Calendar via OAuth2

Runs daily via cron inside a Docker container.

## Project Layout

```
PNS/
├── app/                          # Application code
│   ├── main.py                   # Entry point — orchestrates the 5-step workflow
│   ├── config.py                 # Environment-based configuration (API keys, models, paths)
│   ├── db.py                     # SQLite layer (schema, CRUD, feedback/stats queries)
│   ├── profile_engine.py         # Step 2: generates user profile from feedback history
│   ├── search_client.py          # Step 3: Tavily search + LLM interpretation + dedup
│   ├── calendar_client.py        # Step 5: Google Calendar event creation via OAuth2
│   ├── feedback_cli.py           # CLI tool for reviewing events and rating them
│   └── test_search_locale.py     # Standalone test for the search pipeline
├── data/                         # Runtime persistence (SQLite DB, Google OAuth tokens)
├── crontab                       # Cron schedule (daily at 09:00)
├── docker-compose.yml            # Docker orchestration with env vars
├── Dockerfile                    # Container definition
├── pyproject.toml                # Project metadata
├── requirements.txt              # Python dependencies
├── uv.lock                       # Lock file (uv)
└── env-template.txt              # Environment variable template
```

## Workflow (main.py)

| Step | File              | Description                                      | Internet |
|------|-------------------|--------------------------------------------------|----------|
| 1    | `db.py`           | Initialize SQLite tables                         | No       |
| 2    | `profile_engine.py` | Read feedback from DB → LLM produces user profile | No       |
| 3    | `search_client.py`  | Tavily search → LLM interprets → dedup & filter  | Yes      |
| 4    | `db.py`           | Insert new events into SQLite (skip duplicates)  | No       |
| 5    | `calendar_client.py` | Create Google Calendar events via OAuth2        | Yes      |

## Module Details

### config.py
Central configuration. All values come from environment variables:
- `GEMINI_API_KEY` / `GROQ_API_KEY` — LLM providers
- `TAVILY_API_KEY` — web search API
- `PROFILE_ENGINE` — choose `groq` (default) or `gemini` for profile generation
- `INTERPRETER_ENGINE` — choose LLM for interpreting search results
- `EVENT_LOCATION`, `SEARCH_RADIUS_DAYS` — search parameters
- `DB_PATH`, `GOOGLE_CALENDAR_ID`, Google OAuth paths — persistence

### db.py
SQLite with two tables:
- **eventi** — events with AI score + user feedback score + Google Calendar link; unique on (title, date, venue)
- **profilo_storico** — archives each generated user profile

Key functions:
- `init_db()` — create tables, run migrations
- `insert_evento()` — insert with dedup (returns `True` if new)
- `get_eventi_senza_feedback()` — events awaiting user rating
- `get_feedback_statistics()` — aggregate stats per genre
- `salva_profilo()` / `get_ultimo_profilo()` — profile persistence

### profile_engine.py
Offline LLM call (no search tools):
- Reads recent 50 feedback entries + genre statistics from DB
- Formats data into a prompt with seasonal context (Italian month/season names)
- Calls either **Groq** (default, `llama-3.3-70b-versatile`) or **Gemini** (text-only, no search grounding)
- Produces a concise user profile in Italian (bullet points, 3rd person)
- Saves profile to `profilo_storico` table

### search_client.py
Two-phase architecture replacing the previous Gemini Search Grounding approach (which required billing):

**Phase A — Web Search (Tavily)**
- Builds a query string with date range and location
- Calls Tavily API (free tier: 1000 queries/month, no credit card)
- Returns raw results (title, URL, content snippet)

**Phase B — Interpretation (LLM)**
- Feeds raw search results + user profile into a prompt
- LLM (Gemini or Groq, configured via `INTERPRETER_ENGINE`) extracts structured event data in JSON
- Enforces date range, deduplication, and completeness rules via prompt engineering

**Post-processing:**
- `_filtra_per_data_valida()` — hard filter on valid dates (safety net)
- `_merge_multi_date_events()` — merges events with same title+venue and consecutive dates into multi-day events; non-consecutive events get numbered suffixes (1/N, 2/N, ...)

### calendar_client.py
Google Calendar integration via OAuth2:
- Uses `credentials.json` + `token.json` persisted on Docker volume
- Interactive auth on first run (outside cron), then refreshes tokens automatically
- Creates all-day events with score in title: `[8.5/10] Concert Name`

### feedback_cli.py
CLI for manual user feedback:
- `--list` — show recent 20 events with IDs and scores
- `--set <id> <score>` — assign user rating to an event
- `--review` — interactive loop through unrated events (rate, skip, or quit)

## Configuration via Environment

| Variable               | Default                  | Description                          |
|------------------------|--------------------------|--------------------------------------|
| `GEMINI_API_KEY`       | —                        | Google Gemini API key                |
| `GROQ_API_KEY`         | —                        | Groq API key                         |
| `TAVILY_API_KEY`       | —                        | Tavily web search API key            |
| `PROFILE_ENGINE`       | `groq`                   | LLM for profile generation           |
| `INTERPRETER_ENGINE`   | matches `PROFILE_ENGINE` | LLM for search result interpretation |
| `EVENT_LOCATION`       | —                        | City/area for event search           |
| `SEARCH_RADIUS_DAYS`   | `14`                     | How far ahead to search              |
| `GOOGLE_CALENDAR_ID`   | `primary`                | Target calendar                      |
| `DB_PATH`              | `/data/eventi.db`        | SQLite file path                     |

## Scheduling

Cron (in `crontab`): runs `main.py` daily at 09:00. Output goes to Docker stdout/stderr so it appears in `docker logs`.
