"""Ingesta de Leaguepedia → capa raw.

Flujo:
  1. get_tournaments(year)            → torneos de las ligas configuradas
  2. ingest_tournament(overview_page) → partidas, draft y jugadores de ese torneo

Cada torneo se guarda en su propia ruta determinística:
  raw/leaguepedia/<tabla>/year=<año>/<torneo>.json
Volver a correrlo sobrescribe el mismo archivo (idempotente, sin duplicados).

Nota: si Leaguepedia cambia o renombra un campo, la API responde con error.
Revisa los campos disponibles en https://lol.fandom.com/wiki/Special:CargoTables
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from lolpro.config import Settings, get_settings
from lolpro.ingestion.cargo_client import CargoClient, CargoQuery
from lolpro.storage import RawStore, envelope, slugify

logger = logging.getLogger(__name__)

SOURCE = "leaguepedia"

# --------------------------------------------------------------------------- #
# Campos por tabla. Mantenerlos aquí hace fácil auditarlos y ampliarlos.
# --------------------------------------------------------------------------- #
TOURNAMENT_FIELDS = [
    "Name",
    "OverviewPage",
    "League",
    "Region",
    "Year",
    "Split",
    "DateStart",
    "Date",
    "TournamentLevel",
    "IsQualifier",
    "IsPlayoffs",
    "IsOfficial",
]

# Una fila por partida (game). Team1 = lado azul, Team2 = lado rojo.
GAME_FIELDS = [
    "GameId",
    "MatchId",
    "OverviewPage",
    "Tournament",
    "N_GameInMatch",
    "DateTime_UTC",
    "Patch",
    "Gamelength",
    "Gamelength_Number",
    "Team1",
    "Team2",
    "WinTeam",
    "LossTeam",
    "Winner",
    "Team1Picks",
    "Team2Picks",
    "Team1Bans",
    "Team2Bans",
    "Team1Kills",
    "Team2Kills",
    "Team1Gold",
    "Team2Gold",
    "Team1Towers",
    "Team2Towers",
    "Team1Inhibitors",
    "Team2Inhibitors",
    "Team1Dragons",
    "Team2Dragons",
    "Team1Barons",
    "Team2Barons",
    "Team1RiftHeralds",
    "Team2RiftHeralds",
]

# El draft en orden: bans y picks numerados por equipo, y el rol de cada pick.
DRAFT_FIELDS = (
    [
        "GameId",
        "OverviewPage",
        "Team1",
        "Team2",
        "Winner",
        "Team1PicksByRoleOrder",
        "Team2PicksByRoleOrder",
    ]
    + [f"Team{t}Ban{i}" for t in (1, 2) for i in range(1, 6)]
    + [f"Team{t}Pick{i}" for t in (1, 2) for i in range(1, 6)]
    + [f"Team{t}Role{i}" for t in (1, 2) for i in range(1, 6)]
)

# Una fila por jugador por partida.
PLAYER_FIELDS = [
    "GameId",
    "OverviewPage",
    "DateTime_UTC",
    "Name",
    "Link",
    "Team",
    "Side",
    "Role",
    "Champion",
    "PlayerWin",
    "Kills",
    "Deaths",
    "Assists",
    "Gold",
    "CS",
    "DamageToChampions",
    "VisionScore",
]

TABLES = {
    # nombre lógico: (tabla Cargo, alias, campos)
    "games": ("ScoreboardGames", "SG", GAME_FIELDS),
    "draft": ("PicksAndBansS7", "PB", DRAFT_FIELDS),
    "players": ("ScoreboardPlayers", "SP", PLAYER_FIELDS),
}


def _quote(value: str) -> str:
    """Comillas seguras para el WHERE de Cargo."""
    return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _fields(alias: str, fields: list[str]) -> str:
    # El alias "=Campo" fuerza a Cargo a devolver exactamente ese nombre de clave.
    return ",".join(f"{alias}.{f}={f}" for f in fields)


def _client(settings: Settings) -> CargoClient:
    return CargoClient(
        api_url=settings.leaguepedia_api_url,
        user_agent=settings.user_agent,
        min_interval_s=settings.leaguepedia_min_interval_s,
        page_size=settings.leaguepedia_page_size,
    )


# --------------------------------------------------------------------------- #
# Consultas
# --------------------------------------------------------------------------- #
def tournaments_query(year: int, leagues: list[str]) -> CargoQuery:
    league_list = ",".join(_quote(lg) for lg in leagues)
    return CargoQuery(
        tables="Tournaments=T",
        fields=_fields("T", TOURNAMENT_FIELDS),
        where=f"T.Year = {int(year)} AND T.League IN ({league_list})",
        order_by="T.DateStart",
    )


def table_query(logical_table: str, overview_page: str) -> CargoQuery:
    cargo_table, alias, fields = TABLES[logical_table]
    return CargoQuery(
        tables=f"{cargo_table}={alias}",
        fields=_fields(alias, fields),
        where=f"{alias}.OverviewPage = {_quote(overview_page)}",
        order_by=f"{alias}.GameId",
    )


def leagues_query(year: int) -> CargoQuery:
    return CargoQuery(
        tables="Tournaments=T",
        fields="T.League=League,COUNT(*)=Tournaments",
        where=f'T.Year = {int(year)} AND T.TournamentLevel = "Primary"',
        group_by="T.League",
        order_by="T.League",
    )


# --------------------------------------------------------------------------- #
# Ingesta
# --------------------------------------------------------------------------- #
def list_leagues(year: int, settings: Settings | None = None) -> list[dict]:
    """Útil para descubrir el nombre exacto de cada liga en Leaguepedia."""
    settings = settings or get_settings()
    with _client(settings) as client:
        return client.query(leagues_query(year))


def get_tournaments(
    year: int, settings: Settings | None = None, store: RawStore | None = None
) -> list[dict]:
    """Descarga y guarda la lista de torneos del año. Devuelve las filas."""
    settings = settings or get_settings()
    store = store or RawStore(settings)
    query = tournaments_query(year, settings.leagues)
    with _client(settings) as client:
        rows = client.query(query)

    uri = store.uri(SOURCE, "tournaments", f"year={year}", "tournaments.json")
    store.write_json(uri, envelope(SOURCE, "Tournaments", query.to_params(), rows))
    logger.info("Torneos %s: %d guardados en %s", year, len(rows), uri)
    return rows


def _is_finished(tournament: dict, grace_days: int = 7) -> bool:
    """Un torneo terminado hace más de `grace_days` ya no cambia en Leaguepedia."""
    end = tournament.get("Date")
    if not end:
        return False
    try:
        end_date = datetime.strptime(end[:10], "%Y-%m-%d").date()
    except ValueError:
        return False
    return end_date < date.today() - timedelta(days=grace_days)


def ingest_tournament(
    tournament: dict,
    settings: Settings | None = None,
    store: RawStore | None = None,
    skip_finished: bool = True,
) -> dict[str, int]:
    """Descarga partidas, draft y jugadores de un torneo. Devuelve filas por tabla."""
    settings = settings or get_settings()
    store = store or RawStore(settings)
    overview_page = tournament["OverviewPage"]
    year = str(tournament.get("Year") or "unknown")
    slug = slugify(overview_page)

    counts: dict[str, int] = {}
    with _client(settings) as client:
        for logical_table, (cargo_table, _, _) in TABLES.items():
            uri = store.uri(SOURCE, logical_table, f"year={year}", f"{slug}.json")
            if skip_finished and _is_finished(tournament) and store.exists(uri):
                logger.info("Saltando %s / %s: torneo terminado y ya ingerido", slug, logical_table)
                counts[logical_table] = -1
                continue

            query = table_query(logical_table, overview_page)
            rows = client.query(query)
            store.write_json(uri, envelope(SOURCE, cargo_table, query.to_params(), rows))
            counts[logical_table] = len(rows)
            logger.info("%s / %s: %d filas → %s", slug, logical_table, len(rows), uri)
    return counts


def ingest_year(year: int, settings: Settings | None = None, skip_finished: bool = True) -> dict:
    """Ingesta completa de un año (útil para correr sin Airflow)."""
    settings = settings or get_settings()
    store = RawStore(settings)
    tournaments = get_tournaments(year, settings, store)
    summary = {}
    for t in tournaments:
        summary[t["OverviewPage"]] = ingest_tournament(t, settings, store, skip_finished)
    return summary
