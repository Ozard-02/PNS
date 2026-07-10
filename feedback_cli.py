"""
Mini utility a riga di comando per registrare il feedback dell'utente su un evento,
cioè correggere il punteggio previsto dall'AI con il voto reale.

Uso:
    python feedback_cli.py --list                 # mostra gli ultimi 20 eventi con id e punteggio AI
    python feedback_cli.py --set 12 8.5            # imposta punteggio_utente=8.5 per l'evento id=12
"""
import argparse
from db import get_conn, set_punteggio_utente, init_db


def lista_eventi(limit=20):
    with get_conn() as conn:
        cur = conn.execute(
            """SELECT id, titolo, data, genere_categoria, punteggio_gemini, punteggio_utente
               FROM eventi ORDER BY created_at DESC LIMIT ?""",
            (limit,),
        )
        rows = cur.fetchall()

    print(f"{'ID':<5}{'Titolo':<40}{'Data':<12}{'Genere':<15}{'AI':<6}{'Utente':<6}")
    print("-" * 90)
    for r in rows:
        print(
            f"{r['id']:<5}{r['titolo'][:38]:<40}{r['data']:<12}"
            f"{(r['genere_categoria'] or '')[:13]:<15}"
            f"{r['punteggio_gemini'] or '-':<6}{r['punteggio_utente'] or '-':<6}"
        )


def main():
    parser = argparse.ArgumentParser(description="Gestione feedback eventi")
    parser.add_argument("--list", action="store_true", help="Mostra gli ultimi eventi")
    parser.add_argument(
        "--set", nargs=2, metavar=("EVENTO_ID", "PUNTEGGIO"),
        help="Imposta il punteggio utente per un evento: --set 12 8.5"
    )
    args = parser.parse_args()

    init_db()

    if args.list:
        lista_eventi()
    elif args.set:
        evento_id, punteggio = args.set
        set_punteggio_utente(int(evento_id), float(punteggio))
        print(f"Punteggio utente {punteggio} salvato per evento id={evento_id}")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
