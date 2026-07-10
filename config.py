"""
Configurazione centralizzata del progetto.
Tutti i valori sensibili vengono letti da variabili d'ambiente
(impostate nel file .env / docker-compose.yml).
"""
import os

# --- API Keys ---
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GROQ_API_KEY = os.getenv("GROQ_API_KEY", "")

# --- Scelta del "motore" per lo step 2 (profilo utente + ottimizzazione prompt) ---
# Valori possibili: "gemini" oppure "groq"
PROFILE_ENGINE = os.getenv("PROFILE_ENGINE", "groq").lower()

# --- Modelli ---
GEMINI_SEARCH_MODEL = os.getenv("GEMINI_SEARCH_MODEL", "gemini-2.5-flash")
GEMINI_PROFILE_MODEL = os.getenv("GEMINI_PROFILE_MODEL", "gemini-2.5-flash")
GROQ_MODEL = os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile")

# --- Ricerca eventi ---
LOCATION = os.getenv("EVENT_LOCATION", "")
SEARCH_RADIUS_DAYS = int(os.getenv("SEARCH_RADIUS_DAYS", "14"))

# --- Database ---
DB_PATH = os.getenv("DB_PATH", "/data/eventi.db")

# --- Google Calendar ---
GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "/data/credentials.json")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/data/token.json")
