"""
Mini utility a riga di comando per registrare il feedback dell'utente su un evento,
cioè correggere il punteggio previsto dall'AI con il voto reale.

Uso:
    python feedback_cli.py --list                 # mostra gli ultimi 20 eventi con id e punteggio AI
    python feedback_cli.py --set 12 8.5            # imposta punteggio_utente=8.5 per l'evento id=12
    python feedback_cli.py --review               # loop interattivo su tutti gli eventi NON ancora valutati
    python feedback_cli.py --review --desc         # come sopra, dal più recente al più vecchio
    python feedback_cli.py --queries              # mostra i template di query + statistiche per query
    python feedback_cli.py --propose              # genera ora nuove proposte di query (se ci sono nuovi feedback)
    python feedback_cli.py --propose --force       # come sopra, ignorando i guard (pending/feedback minimi)
    python feedback_cli.py --proposals            # loop interattivo: accetta/rifiuta le proposte di query
"""
import argparse
import os
from config import QUERY_TEMPLATES_PATH
from db import (
    get_conn,
    set_punteggio_utente,
    init_db,
    get_eventi_senza_feedback,
    get_proposte_pending,
    set_stato_proposta,
    get_stats_per_query,
)
from profile_engine import aggiorna_profilo_da_feedback
from query_engine import genera_proposte_query
from query_store import carica_template, salva_template


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
    if valutati > 0:
        aggiorna_profilo_da_feedback()


def mostra_query():
    """Visualizza i template di query attuali con le statistiche di resa per query."""
    template = carica_template()
    stats = {s["query_origine"]: s for s in get_stats_per_query()}

    print(f"\nTemplate di query ({QUERY_TEMPLATES_PATH}):\n")
    for i, t in enumerate(template, 1):
        s = stats.get(t)
        if s:
            resa = (f"eventi trovati: {s['n_eventi']}, valutati: {s['n_valutati']}, "
                    f"media voti utente: {s['avg_user']}")
        else:
            resa = "ancora nessun evento tracciato"
        print(f"  {i}. {t}\n     [{resa}]")
    print()


def _applica_proposta(proposta: dict, template: list[str]) -> list[str]:
    """Applica una proposta accettata alla lista template (senza scrivere il file)."""
    if proposta["azione"] == "aggiungi":
        if proposta["template"] in template:
            print("  -> Già presente nel file: nessuna modifica.")
            return template
        print("  -> Aggiunta in coda al file.")
        return template + [proposta["template"]]

    idx = (proposta.get("indice_target") or 0) - 1
    if not (0 <= idx < len(template)):
        print("  -> Indice non più valido (file cambiato nel frattempo): nessuna modifica.")
        return template
    nuovi = list(template)
    nuovi[idx] = proposta["template"]
    print(f"  -> Template {idx + 1} sostituito nel file.")
    return nuovi


def _stampa_scheda_proposta(proposta: dict, template: list[str], indice: int, totale: int):
    os.system('cls' if os.name == 'nt' else 'clear')
    print("=" * 72)
    print(f"  Proposta {indice}/{totale}  (id={proposta['id']})")
    print("=" * 72)
    if proposta["azione"] == "aggiungi":
        print("  Azione:     AGGIUNGI nuova query")
    else:
        n = proposta.get("indice_target") or 0
        corrente = template[n - 1] if 1 <= n <= len(template) else "(indice non più valido)"
        print(f"  Azione:     SOSTITUISCI query {n}")
        print(f"  Attuale:    {corrente}")
    print(f"  Proposta:   {proposta['template']}")
    if proposta.get("motivazione"):
        print(f"  Motivo AI:  {proposta['motivazione']}")
    print("-" * 72)


def proposals_loop():
    """Scorre le proposte pending una alla volta: accetta (applica al file), rifiuta, salta."""
    proposte = get_proposte_pending()
    if not proposte:
        print("Nessuna proposta in attesa di valutazione.")
        return

    totale = len(proposte)
    print(f"\n{totale} proposte da valutare. Per ciascuna:")
    print("  [a] accetta e applica al file   [r] rifiuta   [s] salta   [q] esci\n")

    template = carica_template()
    valutate = 0

    for i, proposta in enumerate(proposte, 1):
        _stampa_scheda_proposta(proposta, template, i, totale)

        while True:
            risposta = _chiedi_input("  Scelta (a/r/s/q): ").lower()

            if risposta == "q":
                print(f"\nUscita. Valutate {valutate} su {totale}.")
                return

            if risposta == "s":
                break

            if risposta == "r":
                set_stato_proposta(proposta["id"], "rejected")
                print("  -> Rifiutata.")
                valutate += 1
                break

            if risposta == "a":
                nuovi = _applica_proposta(proposta, template)
                if nuovi != template:
                    try:
                        template = salva_template(nuovi)
                    except (ValueError, OSError) as e:
                        print(f"  -> ERRORE scrittura file: {e} (proposta non applicata)")
                        break
                set_stato_proposta(proposta["id"], "accepted")
                print("  -> Accettata.")
                valutate += 1
                break

            print("  Input non valido: usa 'a', 'r', 's' o 'q'.")

    print(f"\nFatto: {valutate} proposte valutate su {totale}.")


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
    parser.add_argument(
        "--queries", action="store_true",
        help="Mostra i template di query con statistiche di resa"
    )
    parser.add_argument(
        "--propose", action="store_true",
        help="Genera ora nuove proposte di query dal modello"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Con --propose: ignora i guard (proposte pending, minimo feedback)"
    )
    parser.add_argument(
        "--proposals", action="store_true",
        help="Loop interattivo: accetta/rifiuta le proposte di query in sospeso"
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
    elif args.queries:
        mostra_query()
    elif args.propose:
        genera_proposte_query(force=args.force)
    elif args.proposals:
        proposals_loop()
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
