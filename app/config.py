"""
Configurazione centralizzata del progetto.
Tutti i valori sensibili vengono letti da variabili d'ambiente
(impostate nel file .env / docker-compose.yml).
"""
import os

# --- API Keys ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Ricerca eventi ---
LOCATION = os.getenv("EVENT_LOCATION", "")
SEARCH_RADIUS_DAYS = int(os.getenv("SEARCH_RADIUS_DAYS", "14"))

# --- Scelta del "motore" per lo step 2 (profilo utente + ottimizzazione prompt) ---
# Valori possibili: "gemini" oppure "groq"
PROFILE_ENGINE = os.getenv("PROFILE_ENGINE", "groq").lower()

# --- Modelli ---
GEMINI_SEARCH_MODEL = os.getenv("GEMINI_SEARCH_MODEL", "gemini-flash-latest")
GEMINI_PROFILE_MODEL = os.getenv("GEMINI_PROFILE_MODEL", "gemini-flash-latest")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Tavily (ricerca web, free tier 1000 query/mese, no carta) ---
TAVILY_API_KEY = os.getenv("TAVILY_API_KEY", "")

# --- Modello usato per interpretare i risultati Tavily e strutturarli in JSON ---
# Riusa lo stesso motore scelto per il profilo (gemini o groq), ma è configurabile a parte
INTERPRETER_ENGINE = os.getenv("INTERPRETER_ENGINE", PROFILE_ENGINE).lower()

# --- Ricerca eventi ---
LOCATION = os.getenv("EVENT_LOCATION", "")
SEARCH_RADIUS_DAYS = int(os.getenv("SEARCH_RADIUS_DAYS", "14"))
TAVILY_MAX_RESULTS = int(os.getenv("TAVILY_MAX_RESULTS", "05"))

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "/data/eventi.db")

# --- Google Calendar ---
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "/data/credentials.json")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/data/token.json")
