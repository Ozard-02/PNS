"""
Step 5 del workflow: inserimento eventi su Google Calendar.

Usa OAuth2 (credentials.json + token.json persistiti su volume Docker).
Al primo avvio va fatta l'autenticazione manuale una tantum (vedi README).
"""
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
import os

from config import GOOGLE_CALENDAR_ID, GOOGLE_CREDENTIALS_PATH, GOOGLE_TOKEN_PATH

SCOPES = ["https://www.googleapis.com/auth/calendar.events"]


def _get_credentials() -> Credentials:
    creds = None
    if os.path.exists(GOOGLE_TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(GOOGLE_TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            # Richiede un'autenticazione interattiva (da fare una tantum, non in cron)
            flow = InstalledAppFlow.from_client_secrets_file(
                GOOGLE_CREDENTIALS_PATH, SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open(GOOGLE_TOKEN_PATH, "w") as f:
            f.write(creds.to_json())

    return creds


def _get_service():
    creds = _get_credentials()
    return build("calendar", "v3", credentials=creds)


def crea_evento_calendario(evento: dict) -> str | None:
    """
    Crea un evento su Google Calendar. Ritorna l'ID dell'evento creato, o None in caso di errore.
    Il titolo include il punteggio predetto, es: "[8.5/10] Concerto Rock".
    """
    service = _get_service()

    punteggio = evento.get("punteggio_gemini")
    titolo_calendario = f"[{punteggio}/10] {evento['titolo']}" if punteggio else evento["titolo"]

    descrizione = (
        f"Genere: {evento.get('genere_categoria', 'N/D')}\n"
        f"Motivazione punteggio: {evento.get('motivazione_punteggio', 'N/D')}\n"
        f"Info/Biglietti: {evento.get('link_info', 'N/D')}"
    )

    body = {
        "summary": titolo_calendario,
        "location": evento.get("luogo", ""),
        "description": descrizione,
        "start": {"date": evento["data"]},  # evento "tutto il giorno"
        "end": {"date": evento["data"]},
    }

    try:
        created = service.events().insert(
            calendarId=GOOGLE_CALENDAR_ID, body=body
        ).execute()
        return created.get("id")
    except Exception as e:
        print(f"[calendar_client] Errore creazione evento '{evento['titolo']}': {e}")
        return None
