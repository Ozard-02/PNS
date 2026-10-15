import os

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY", "")
OPENROUTER_MODEL = os.getenv("OPENROUTER_MODEL", "nvidia/nemotron-3-super-120b-a12b:free")

# Istanza LLM locale (es. Unsloth su LAN, API OpenAI-compatible).
# Se LOCAL_LLM_URL è impostato, llm_client la prova per prima e ripiega su
# OpenRouter solo in caso di errore. Chiave solo via env, mai nel codice.
LOCAL_LLM_URL = os.getenv("LOCAL_LLM_URL", "")
LOCAL_API_KEY = os.getenv("LOCAL_API_KEY", "")
LOCAL_MODEL = os.getenv("LOCAL_MODEL", "unsloth/Qwen3-8B-GGUF")

LOCATION = os.getenv("EVENT_LOCATION", "")
SEARCH_RADIUS_DAYS = int(os.getenv("SEARCH_RADIUS_DAYS", "14"))
SEARCH_MAX_RESULTS = int(os.getenv("SEARCH_MAX_RESULTS", "5"))

DB_PATH = os.getenv("DB_PATH", "/data/eventi.db")

QUERY_TEMPLATES_PATH = os.getenv("QUERY_TEMPLATES_PATH", "/data/query_templates.txt")

GOOGLE_CALENDAR_ID = os.getenv("GOOGLE_CALENDAR_ID", "primary")
GOOGLE_CREDENTIALS_PATH = os.getenv("GOOGLE_CREDENTIALS_PATH", "/data/credentials.json")
GOOGLE_TOKEN_PATH = os.getenv("GOOGLE_TOKEN_PATH", "/data/token.json")
