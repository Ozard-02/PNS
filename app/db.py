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
    query_origine TEXT DEFAULT NULL,
    created_at TEXT NOT NULL,
    feedback_updated_at TEXT DEFAULT NULL,
    UNIQUE(titolo, data, luogo)
);

CREATE TABLE IF NOT EXISTS profilo_storico (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    generato_il TEXT NOT NULL,
    contenuto TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS query_proposals (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    template TEXT NOT NULL,
    motivazione TEXT,
    azione TEXT NOT NULL,
    indice_target INTEGER DEFAULT NULL,
    stato TEXT NOT NULL DEFAULT 'pending',
    created_at TEXT NOT NULL
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
        try:
            conn.execute("ALTER TABLE eventi ADD COLUMN query_origine TEXT DEFAULT NULL")
        except sqlite3.OperationalError:
            pass  # colonna già presente (DB creati prima di questa versione)


def insert_evento(evento: dict) -> bool:
    with get_conn() as conn:
        try:
            conn.execute(
                """INSERT INTO eventi
                   (titolo, data, data_fine, luogo, link_info, genere_categoria,
                    punteggio_gemini, motivazione_punteggio, query_origine, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    evento.get("titolo"),
                    evento.get("data"),
                    evento.get("data_fine"),
                    evento.get("luogo"),
                    evento.get("link_info"),
                    evento.get("genere_categoria"),
                    evento.get("punteggio_predetto"),
                    evento.get("motivazione_punteggio"),
                    evento.get("template_origine"),
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            return True
        except sqlite3.IntegrityError:
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
    order = "ASC" if order.upper() != "DESC" else "DESC"
    with get_conn() as conn:
        cur = conn.execute(
            f"""SELECT * FROM eventi
                WHERE punteggio_utente IS NULL
                ORDER BY data {order}"""
        )
        return [dict(row) for row in cur.fetchall()]


def get_feedback_statistics():
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
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT titolo, genere_categoria, punteggio_gemini, punteggio_utente, data,
                      motivazione_punteggio, luogo
               FROM eventi
               WHERE punteggio_utente IS NOT NULL
                 AND feedback_updated_at > ?
               ORDER BY feedback_updated_at""",
            (data_da,),
        )
        return [dict(row) for row in cur.fetchall()]


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


def get_data_ultimo_profilo() -> str | None:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT generato_il FROM profilo_storico ORDER BY generato_il DESC LIMIT 1"
        )
        row = cur.fetchone()
        return row["generato_il"] if row else None


STATI_PROPOSTA = ("pending", "accepted", "rejected")
AZIONI_PROPOSTA = ("aggiungi", "sostituisci")


def salva_proposta(template: str, motivazione: str, azione: str, indice_target=None) -> int:
    """Salva una proposta di query come 'pending'. Ritorna l'id assegnato."""
    if azione not in AZIONI_PROPOSTA:
        raise ValueError(f"Azione non valida: {azione!r}")
    with get_conn() as conn:
        cur = conn.execute(
            """INSERT INTO query_proposals
               (template, motivazione, azione, indice_target, stato, created_at)
               VALUES (?, ?, ?, ?, 'pending', ?)""",
            (template, motivazione, azione, indice_target,
             datetime.now(timezone.utc).isoformat()),
        )
        return cur.lastrowid


def get_proposte_pending() -> list[dict]:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT * FROM query_proposals WHERE stato = 'pending' ORDER BY id"
        )
        return [dict(row) for row in cur.fetchall()]


def conta_proposte_pending() -> int:
    with get_conn() as conn:
        cur = conn.execute(
            "SELECT COUNT(*) as n FROM query_proposals WHERE stato = 'pending'"
        )
        return cur.fetchone()["n"]


def set_stato_proposta(proposta_id: int, stato: str):
    if stato not in STATI_PROPOSTA:
        raise ValueError(f"Stato non valido: {stato!r}")
    with get_conn() as conn:
        conn.execute(
            "UPDATE query_proposals SET stato = ? WHERE id = ?",
            (stato, proposta_id),
        )


def get_data_ultima_proposta() -> str | None:
    with get_conn() as conn:
        cur = conn.execute("SELECT MAX(created_at) as ultima FROM query_proposals")
        return cur.fetchone()["ultima"]


def get_stats_per_query() -> list[dict]:
    """Per ogni template che ha prodotto eventi: n_eventi, n_valutati, media voti utente."""
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT
                   query_origine,
                   COUNT(*) as n_eventi,
                   COUNT(punteggio_utente) as n_valutati,
                   ROUND(AVG(punteggio_utente), 2) as avg_user
                FROM eventi
                WHERE query_origine IS NOT NULL
                GROUP BY query_origine
                ORDER BY n_eventi DESC"""
        )
        return [dict(row) for row in cur.fetchall()]
