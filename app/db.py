"""
Gestione del database SQLite locale.
Tabella principale: eventi (con punteggio_gemini e punteggio_utente per il feedback loop).
"""
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone

from config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS eventi (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    titolo TEXT NOT NULL,
    data TEXT NOT NULL,
    luogo TEXT,
    link_info TEXT,
    genere_categoria TEXT,
    punteggio_gemini REAL,
    motivazione_punteggio TEXT,
    punteggio_utente REAL DEFAULT NULL,
    calendar_event_id TEXT,
    created_at TEXT NOT NULL,
    UNIQUE(titolo, data, luogo)
);

CREATE TABLE IF NOT EXISTS profilo_storico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generato_il TEXT NOT NULL,
    contenuto TEXT NOT NULL
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def insert_evento(evento: dict) -> bool:
    """Inserisce un evento, ignora se già presente (stesso titolo+data+luogo). Ritorna True se inserito."""
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO eventi
                   (titolo, data, luogo, link_info, genere_categoria,
                    punteggio_gemini, motivazione_punteggio, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evento.get("titolo"),
                    evento.get("data"),
                    evento.get("luogo"),
                    evento.get("link_info"),
                    evento.get("genere_categoria"),
                    evento.get("punteggio_predetto"),
                    evento.get("motivazione_punteggio"),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return True
        except sqlite3.IntegrityError:
            # Evento duplicato (stesso titolo, data, luogo) -> ignorato
            return False


def update_calendar_event_id(evento_id: int, calendar_event_id: str):
    with get_conn() as conn:
        conn.execute(
            "UPDATE eventi SET calendar_event_id = ? WHERE id = ?",
            (calendar_event_id, evento_id),
        )


def get_eventi_senza_calendario():
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM eventi WHERE calendar_event_id IS NULL"
        )
        return [dict(row) for row in cur.fetchall()]


def get_feedback_recente(limit: int = 50):
    """Ritorna gli eventi con un punteggio_utente esplicito (feedback), i più recenti prima."""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT titolo, genere_categoria, punteggio_gemini, punteggio_utente, data
               FROM eventi
               WHERE punteggio_utente IS NOT NULL
               ORDER BY created_at DESC
               LIMIT ?""",
            (limit,),
        )
        return [dict(row) for row in cur.fetchall()]


def set_punteggio_utente(evento_id: int, punteggio: float):
    with get_conn() as conn:
        conn.execute(
            "UPDATE eventi SET punteggio_utente = ? WHERE id = ?",
            (punteggio, evento_id),
        )


def salva_profilo(contenuto: str):
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO profilo_storico (generato_il, contenuto) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), contenuto),
        )


def get_ultimo_profilo() -> str | None:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT contenuto FROM profilo_storico ORDER BY generato_il DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row["contenuto"] if row else None
