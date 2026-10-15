# AI Event & Concert Tracker

Automated pipeline that searches for local events and concerts, scores them against a
learned user profile, and pushes matches to Google Calendar. Runs daily via cron inside
a Docker container.

## How it works

```
Cron (daily)
  -> profile_engine   : reads feedback history from SQLite, aggregates per-genre
                         statistics, generates an updated user-preference summary
                         (OpenRouter free model, no web access), enriched with seasonal
                         context and correction-direction analysis (↑/↓/→)
  -> search_client     : DuckDuckGo HTML fetch searches the web for events (no API key),
                          then OpenRouter structures the raw results into JSON, scored against
                          the user profile; multi-date events (same title + venue) are
                          merged — consecutive dates become a single multi-day event,
                          non-consecutive ones are numbered (1/N)
  -> db                : new events are stored with optional data_fine column for
                          multi-day events, duplicates are skipped; each event records
                          which query template found it (query_origine)
  -> calendar_client    : new events are pushed to Google Calendar; multi-day events
                          are created as all-day blocks spanning data → data_fine
  -> query_engine       : proposes query template improvements from feedback
                          (non-fatal step, proposals only — you accept/reject in the TUI)
```

The scoring engine improves over time: correcting an event's score through the feedback
CLI feeds back into the next day's profile generation.

## Requirements

- Docker and Docker Compose
- OpenRouter API key (https://openrouter.ai/keys, free tier, no billing required for
  `:free` models) - used for profile generation and result interpretation
- A Google Cloud project with the Calendar API enabled, plus an OAuth2 client
  (Desktop app type)

## Setup

1. Copy the environment template and fill in the values:

   ```bash
   cp .env.example .env
   ```

2. Create OAuth2 credentials for Google Calendar in the Google Cloud Console
   (APIs & Services -> Credentials -> Create Credentials -> OAuth client ID -> Desktop
   app). Download the JSON and save it as `data/credentials.json`.

3. Run the OAuth flow once, locally, to generate `data/token.json` (this requires a
   browser and cannot be done inside the container):

   ```bash
   pip install -r requirements.txt
   python -c "from calendar_client import _get_credentials; _get_credentials()"
   ```

4. Build and start the container:

   ```bash
   docker compose up -d --build
   ```

The container runs `cron -f` in the foreground and executes `main.py` daily at 07:00
(timezone set in the Dockerfile).

## Manual run

```bash
docker exec -it ai-event-tracker python /app/main.py
```

## Feedback loop

Correct a predicted score to teach the system your actual preferences:

```bash
docker exec -it ai-event-tracker python /app/feedback_cli.py --list
docker exec -it ai-event-tracker python /app/feedback_cli.py --set <event_id> <score>
```

The next run reads this feedback and adjusts the generated user profile accordingly.

## Query templates

Search queries live in `/data/query_templates.txt` (one per line, `#` comments,
placeholders `{location} {mese_anno} {oggi} {fine}`) — created with defaults on
first run, survives rebuilds. Edit it by hand (`docker cp` it out and back) or
let the model propose improvements and evaluate them in the TUI:

```bash
docker exec -it ai-event-tracker python /app/feedback_cli.py --queries    # show templates + per-query stats
docker exec -it ai-event-tracker python /app/feedback_cli.py --propose    # generate proposals now
docker exec -it ai-event-tracker python /app/feedback_cli.py --proposals  # accept/reject loop
```

The daily run auto-generates proposals when there are ≥3 new rated events and no
pending proposals; nothing is applied without your approval.

## Local testing without Docker

```bash
pip install -r requirements.txt
export OPENROUTER_API_KEY="..."
python test_search_locale.py
```

This exercises only the search/interpretation step, without touching the database or
Google Calendar.

## Configuration reference

| Variable | Description | Default |
|---|---|---|
| `OPENROUTER_API_KEY` | OpenRouter API key (`:free` models, no billing) | - |
| `OPENROUTER_MODEL` | Model for profile generation + result interpretation | `nvidia/nemotron-3-super-120b-a12b:free` |
| `EVENT_LOCATION` | Location string used in search queries | - |
| `SEARCH_RADIUS_DAYS` | How many days ahead to search | `14` |
| `SEARCH_MAX_RESULTS` | Max results per web-search query | `5` |
| `QUERY_TEMPLATES_PATH` | Editable search query templates file | `/data/query_templates.txt` |
| `GOOGLE_CALENDAR_ID` | Target calendar ID | `primary` |
| `DB_PATH` | SQLite file path inside the container | `/data/eventi.db` |

## Project layout

```
app/
  config.py           configuration from environment variables
  db.py               SQLite schema and CRUD helpers
  profile_engine.py    reads feedback history + per-genre statistics, generates
                         the user profile with seasonal context
  search_client.py     DuckDuckGo fetch + OpenRouter structuring, with date validation,
                         multi-date event merging and query-origin tagging
  query_store.py       load/save/validate search query templates (persistent file)
  query_engine.py      proposes query template improvements from feedback
  calendar_client.py   Google Calendar integration, supports multi-day all-day events
  llm_client.py        single OpenRouter caller (profile + interpretation)
  feedback_cli.py       CLI to record user feedback on past events
  main.py               orchestrates the daily run
Dockerfile
docker-compose.yml
crontab
requirements.txt
test_search_locale.py   standalone search test, no DB/Calendar side effects
```

## Notes

- OpenRouter `:free` models have daily/rate limits and availability changes
  periodically; if requests start failing with 429 errors, switch `OPENROUTER_MODEL`
  to another `:free` model via env (no code change needed).
- DuckDuckGo HTML scraping can break if their markup changes or requests get
  throttled; `search_client.py` skips failed pages/queries and returns `[]` when
  nothing is found, so a bad day degrades to zero new events instead of a crash.
- `search_client.py` validates every event's date against the requested search window
  and discards anything out of range or unparsable, independent of what the LLM returns.
- **Multi-date merging**: after date validation, events with the same title (fuzzy
  match, 0.95 threshold) and venue are grouped. If their dates form a consecutive
  block, they become a single multi-day event (`data_fine` set). Otherwise they are
  kept as separate calendar events with a `(1/N)` suffix on the title.

## License

MIT
