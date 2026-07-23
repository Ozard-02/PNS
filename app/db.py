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
    data_fine TEXT DEFAULT NULL,
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

MIGRATIONS = [
    "ALTER TABLE eventi ADD COLUMN data_fine TEXT DEFAULT NULL",
    "ALTER TABLE eventi ADD COLUMN feedback_updated_at TEXT DEFAULT NULL",
]


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
        for migrazione in MIGRATIONS:
            try:
                conn.execute(migrazione)
            except sqlite3.OperationalError:
                pass


def insert_evento(evento: dict) -> bool:
    """Inserisce un evento, ignora se già presente (stesso titolo+data+luogo). Ritorna True se inserito."""
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO eventi
                   (titolo, data, data_fine, luogo, link_info, genere_categoria,
                    punteggio_gemini, motivazione_punteggio, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evento.get("titolo"),
                    evento.get("data"),
                    evento.get("data_fine"),
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


def get_eventi_senza_feedback(order: str = "ASC"):
    """Ritorna tutti gli eventi con punteggio_utente ancora NULL (da revisionare)."""
    order = "ASC" if order.upper() != "DESC" else "DESC"
    with get_conn() as conn:
        cur = conn.execute(
            f"""SELECT * FROM eventi
                WHERE punteggio_utente IS NULL
                ORDER BY data {order}"""
        )
        return [dict(row) for row in cur.fetchall()]


def get_feedback_statistics():
    """Ritorna statistiche aggregate per genere basate sui feedback utente."""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT
                   genere_categoria,
                   COUNT(*) as count,
                   ROUND(AVG(punteggio_gemini), 2) as avg_ai,
                   ROUND(AVG(punteggio_utente), 2) as avg_user,
                   ROUND(AVG(punteggio_utente - punteggio_gemini), 2) as avg_correzione,
                   MIN(punteggio_utente) as min_user,
                   MAX(punteggio_utente) as max_user,
                   MAX(created_at) as ultimo_feedback
               FROM eventi
               WHERE punteggio_utente IS NOT NULL
               GROUP BY genere_categoria
               ORDER BY count DESC"""
        )
        stats = [dict(row) for row in cur.fetchall()]

        cur2 = conn.execute(
            """SELECT
                   COUNT(*) as totale_feedback,
                   ROUND(AVG(punteggio_gemini), 2) as avg_ai_globale,
                   ROUND(AVG(punteggio_utente), 2) as avg_user_globale,
                   ROUND(AVG(punteggio_utente - punteggio_gemini), 2) as avg_correzione_globale
               FROM eventi
               WHERE punteggio_utente IS NOT NULL"""
        )
        totali = dict(cur2.fetchone())
        return {"per_genere": stats, "totali": totali}


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
            "UPDATE eventi SET punteggio_utente = ?, feedback_updated_at = ? WHERE id = ?",
            (punteggio, datetime.now(timezone.utc).isoformat(), evento_id),
        )


def get_feedback_da_data(data_da: str) -> list[dict]:
    """Ritorna tutti i feedback con punteggio_utente impostato dopo una certa data."""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT titolo, genere_categoria, punteggio_gemini, punteggio_utente, data,
                      motivazione_punteggio, luogo
               FROM eventi
               WHERE punteggio_utente IS NOT NULL
                 AND (feedback_updated_at IS NOT NULL AND feedback_updated_at > ?)
               ORDER BY feedback_updated_at""",
            (data_da,),
        )
        return [dict(row) for row in cur.fetchall()]


def get_data_ultimo_feedback() -> str | None:
    """Ritorna il timestamp ISO del feedback_updated_at più recente, o None."""
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT MAX(feedback_updated_at) as ultimo FROM eventi WHERE punteggio_utente IS NOT NULL"
        )
        row = cur.fetchone()
        return row["ultimo"] if row and row["ultimo"] else None


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
