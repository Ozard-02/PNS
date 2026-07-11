"""
Mini utility a riga di comando per registrare il feedback dell'utente su un evento,
cioè correggere il punteggio previsto dall'AI con il voto reale.

Uso:
    python feedback_cli.py --list                 # mostra gli ultimi 20 eventi con id e punteggio AI
    python feedback_cli.py --set 12 8.5            # imposta punteggio_utente=8.5 per l'evento id=12
    python feedback_cli.py --review               # loop interattivo su tutti gli eventi NON ancora valutati
    python feedback_cli.py --review --desc         # come sopra, dal più recente al più vecchio
"""
import argparse
import os
from db import (
    get_conn,
    set_punteggio_utente,
    init_db,
    get_eventi_senza_feedback,
)


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


def _stampa_scheda_evento(evento: dict, indice: int, totale: int):
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 72)
    print(f"  Evento {indice}/{totale}  (id={evento['id']})")
    print("=" * 72)
    print(f"  Titolo:     {evento['titolo']}")
    print(f"  Data:       {evento['data']}")
    print(f"  Luogo:      {evento.get('luogo') or '-'}")
    print(f"  Genere:     {evento.get('genere_categoria') or '-'}")
    print(f"  Punt. AI:   {evento.get('punteggio_gemini')}")
    if evento.get("motivazione_punteggio"):
        print(f"  Motivo AI:  {evento['motivazione_punteggio']}")
    if evento.get("link_info"):
        print(f"  Link:       {evento['link_info']}")
    print("-" * 72)


def _chiedi_input(prompt: str) -> str:
    try:
        return input(prompt).strip()
    except EOFError:
        return "q"


def review_loop(order: str = "asc"):
    """
    Scorre uno per uno tutti gli eventi con punteggio_utente ancora NULL, forzando
    una decisione (voto, salta, o esci) per ciascuno prima di passare al successivo.
    """
    eventi = get_eventi_senza_feedback(order="DESC" if order == "desc" else "ASC")

    if not eventi:
        print("Nessun evento in attesa di valutazione: sei già aggiornato.")
        return

    totale = len(eventi)
    print(f"\n{totale} eventi da valutare. Per ciascuno inserisci un voto da 1 a 10,")
    print("oppure: [s] salta per ora   [q] esci e salva progressi fin qui\n")

    valutati = 0
    saltati = 0

    for i, evento in enumerate(eventi, 1):
        _stampa_scheda_evento(evento, i, totale)

        while True:
            risposta = _chiedi_input("  Voto (1-10) / s=salta / q=esci: ").lower()

            if risposta == "q":
                print(f"\nUscita. Valutati {valutati}, saltati {saltati}, "
                      f"rimasti {totale - i}.")
                return

            if risposta == "s":
                saltati += 1
                break

            try:
                voto = float(risposta.replace(",", "."))
            except ValueError:
                print("  Input non valido: inserisci un numero (es. 7.5), 's' o 'q'.")
                continue

            if not (1 <= voto <= 10):
                print("  Il voto deve essere tra 1 e 10.")
                continue

            set_punteggio_utente(evento["id"], voto)
            print(f"  -> Salvato: punteggio_utente = {voto}")
            valutati += 1
            break

    print(f"\nRevisione completata: {valutati} valutati, {saltati} saltati su {totale}.")


def main():
    parser = argparse.ArgumentParser(description="Gestione feedback eventi")
    parser.add_argument("--list", action="store_true", help="Mostra gli ultimi eventi")
    parser.add_argument(
        "--set", nargs=2, metavar=("EVENTO_ID", "PUNTEGGIO"),
        help="Imposta il punteggio utente per un evento: --set 12 8.5"
    )
    parser.add_argument(
        "--review", action="store_true",
        help="Loop interattivo su tutti gli eventi NON ancora valutati (uno alla volta)"
    )
    parser.add_argument(
        "--desc", action="store_true",
        help="In modalità --review, parti dagli eventi più recenti invece che dai più vecchi"
    )
    args = parser.parse_args()

    init_db()

    if args.list:
        lista_eventi()
    elif args.set:
        evento_id, punteggio = args.set
        set_punteggio_utente(int(evento_id), float(punteggio))
        print(f"Punteggio utente {punteggio} salvato per evento id={evento_id}")
    elif args.review:
        review_loop(order="desc" if args.desc else "asc")
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
