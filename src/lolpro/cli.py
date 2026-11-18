"""Línea de comandos para correr la ingesta sin Airflow.

Ejemplos:
    lolpro list-leagues --year 2026
    lolpro tournaments --year 2026
    lolpro ingest --year 2026
    lolpro ingest --year 2026 --tournament "LCK/2026 Season/Rounds 1-2"
"""

from __future__ import annotations

import argparse
import json
import logging

from lolpro.ingestion import leaguepedia


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="lolpro")
    parser.add_argument("-v", "--verbose", action="store_true")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("list-leagues", help="Lista los nombres exactos de ligas en Leaguepedia")
    p.add_argument("--year", type=int, required=True)

    p = sub.add_parser("tournaments", help="Descarga la lista de torneos del año")
    p.add_argument("--year", type=int, required=True)

    p = sub.add_parser("ingest", help="Ingesta partidas, draft y jugadores")
    p.add_argument("--year", type=int, required=True)
    p.add_argument("--tournament", help="OverviewPage de un solo torneo (opcional)")
    p.add_argument("--full-refresh", action="store_true", help="No saltar torneos terminados")

    args = parser.parse_args(argv)
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    if args.command == "list-leagues":
        for row in leaguepedia.list_leagues(args.year):
            print(f"{row.get('Tournaments', '?'):>4}  {row.get('League')}")

    elif args.command == "tournaments":
        rows = leaguepedia.get_tournaments(args.year)
        for t in rows:
            print(f"{t.get('DateStart', '')[:10]}  {t['OverviewPage']}")

    elif args.command == "ingest":
        skip = not args.full_refresh
        if args.tournament:
            tournaments = leaguepedia.get_tournaments(args.year)
            match = [t for t in tournaments if t["OverviewPage"] == args.tournament]
            if not match:
                raise SystemExit(f"No encontré '{args.tournament}'. Usa: lolpro tournaments")
            result = {args.tournament: leaguepedia.ingest_tournament(match[0], skip_finished=skip)}
        else:
            result = leaguepedia.ingest_year(args.year, skip_finished=skip)
        print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
