# AI Event & Concert Tracker

Automated pipeline that searches for local events and concerts, scores them against a
learned user profile, and pushes matches to Google Calendar. Runs daily via cron inside
a Docker container.

## How it works

```
Cron (daily)
  -> profile_engine   : reads feedback history from SQLite, generates an updated
                         user-preference summary (Groq or Gemini, no web access)
  -> search_client     : Tavily searches the web for events, then an LLM (Groq or
                          Gemini) structures the raw results into JSON, scored against
                          the user profile
  -> db                : new events are stored, duplicates are skipped
  -> calendar_client    : new events are pushed to Google Calendar
```

The scoring engine improves over time: correcting an event's score through the feedback
CLI feeds back into the next day's profile generation.

## Requirements

- Docker and Docker Compose
- Gemini API key (https://aistudio.google.com/apikey)
- Groq API key (https://console.groq.com/keys) - used for profile generation and/or
  result interpretation, selectable independently via env vars
- Tavily API key (https://tavily.com) - web search, free tier does not require billing
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

## Local testing without Docker

```bash
pip install -r requirements.txt
export GEMINI_API_KEY="..."
export TAVILY_API_KEY="..."
export GROQ_API_KEY="..."
python test_search_locale.py
```

This exercises only the search/interpretation step, without touching the database or
Google Calendar.

## Configuration reference

| Variable | Description | Default |
|---|---|---|
| `GEMINI_API_KEY` | Gemini API key | - |
| `GROQ_API_KEY` | Groq API key | - |
| `TAVILY_API_KEY` | Tavily API key | - |
| `PROFILE_ENGINE` | Backend for profile generation: `groq` or `gemini` | `groq` |
| `INTERPRETER_ENGINE` | Backend for structuring search results: `groq` or `gemini` | value of `PROFILE_ENGINE` |
| `GEMINI_SEARCH_MODEL` | Gemini model used where applicable | `gemini-flash-latest` |
| `GEMINI_PROFILE_MODEL` | Gemini model used for profile/interpretation | `gemini-flash-latest` |
| `GROQ_MODEL` | Groq model used for profile/interpretation | `llama-3.3-70b-versatile` |
| `EVENT_LOCATION` | Location string used in search queries | - |
| `SEARCH_RADIUS_DAYS` | How many days ahead to search | `14` |
| `TAVILY_MAX_RESULTS` | Max results per Tavily search | `10` |
| `GOOGLE_CALENDAR_ID` | Target calendar ID | `primary` |
| `DB_PATH` | SQLite file path inside the container | `/data/eventi.db` |

## Project layout

```
app/
  config.py           configuration from environment variables
  db.py               SQLite schema and CRUD helpers
  profile_engine.py    reads feedback history, generates the user profile
  search_client.py     Tavily search + LLM-based structuring, with date validation
  calendar_client.py   Google Calendar integration
  feedback_cli.py       CLI to record user feedback on past events
  main.py               orchestrates the daily run
Dockerfile
docker-compose.yml
crontab
requirements.txt
test_search_locale.py   standalone search test, no DB/Calendar side effects
```

## Notes

- Free-tier rate limits for Gemini, Groq, and Tavily change periodically; check each
  provider's documentation if requests start failing with 429 errors.
- Search Grounding on the Gemini API requires a billing-enabled Google Cloud project
  even for its free monthly allocation; this project avoids that requirement by using
  Tavily for search instead.
- `search_client.py` validates every event's date against the requested search window
  and discards anything out of range or unparsable, independent of what the LLM returns.

## License

MIT
