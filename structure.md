# PNS — AI Event & Concert Tracker

## Overview

Automated pipeline that:
1. Reads historical user feedback from SQLite → generates an updated user profile (offline LLM)
2. Searches the web for events/concerts via direct fetch, using editable query templates
3. Interprets raw search results into structured JSON via a second LLM (tags each event with the query template that found it)
4. Stores new events in SQLite (dedup by title + date + venue)
5. Syncs new events to Google Calendar via OAuth2
6. Evolves the query templates from feedback (proposes only — user accepts/rejects in TUI)

Runs daily via cron inside a Docker container.

## Project Layout

```
PNS/
├── app/                          # Application code
│   ├── main.py                   # Entry point — orchestrates the 6-step workflow
│   ├── config.py                 # Environment-based configuration (API keys, models, paths)
│   ├── db.py                     # SQLite layer (schema, CRUD, feedback/stats, query proposals)
│   ├── llm_client.py             # Single OpenRouter caller used by profile_engine + search_client
│   ├── profile_engine.py         # Step 2: generates user profile from feedback history
│   ├── query_store.py            # Load/save/validate search query templates (/data file)
│   ├── query_engine.py           # Step 6: proposes query improvements from feedback (pending review)
│   ├── search_client.py          # Step 3: template-driven fetch + LLM interpretation + dedup
│   ├── calendar_client.py        # Step 5: Google Calendar event creation via OAuth2
│   └── feedback_cli.py           # CLI tool for reviewing events, queries and proposals
├── data/                         # Runtime persistence (SQLite DB, Google OAuth tokens, query_templates.txt)
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
| 2    | `profile_engine.py` | Read feedback from DB → OpenRouter produces user profile | No       |
| 3    | `search_client.py`  | Template-driven fetch → OpenRouter interprets → dedup & filter | Yes      |
| 4    | `db.py`           | Insert new events into SQLite (skip duplicates)  | No       |
| 5    | `calendar_client.py` | Create Google Calendar events via OAuth2        | Yes      |
| 6    | `query_engine.py` | Propose query improvements from feedback (non-fatal, pending review) | Yes |

## Configuration via Environment

| Variable               | Default                                        | Description                          |
|------------------------|-----------------------------------------------|--------------------------------------|
| `OPENROUTER_API_KEY`   | —                                             | OpenRouter API key (free `:free` models, no billing) |
| `OPENROUTER_MODEL`     | `nvidia/nemotron-3-super-120b-a12b:free`      | OpenRouter model for profile + interpretation |
| `EVENT_LOCATION`       | —                                             | City/area for event search           |
| `SEARCH_RADIUS_DAYS`   | `14`                                          | How far ahead to search              |
| `GOOGLE_CALENDAR_ID`   | `primary`                                     | Target calendar                      |
| `DB_PATH`              | `/data/eventi.db`                             | SQLite file path                     |
| `SEARCH_MAX_RESULTS`   | `5`                                           | Max results per web-search query     |
| `QUERY_TEMPLATES_PATH` | `/data/query_templates.txt`                   | Editable search query templates file |

## Scheduling

Cron (in `crontab`): runs `main.py` daily at 09:00. Output goes to Docker stdout/stderr so it appears in `docker logs`.
