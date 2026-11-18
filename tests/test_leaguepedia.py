from datetime import date, timedelta

import httpx
import respx

from lolpro.ingestion import leaguepedia
from lolpro.storage import RawStore
from tests.conftest import API, cargo_payload

TOURNAMENT = {
    "Name": "LCK 2026 Rounds 1-2",
    "OverviewPage": "LCK/2026 Season/Rounds 1-2",
    "League": "LoL Champions Korea",
    "Year": "2026",
    "Date": "2026-06-01",
}


def route_by_table(request: httpx.Request) -> httpx.Response:
    tables = request.url.params["tables"]
    if tables.startswith("Tournaments"):
        return httpx.Response(200, json=cargo_payload([TOURNAMENT]))
    if tables.startswith("ScoreboardGames"):
        return httpx.Response(200, json=cargo_payload([{"GameId": "g1", "Winner": "1"}]))
    if tables.startswith("PicksAndBansS7"):
        return httpx.Response(200, json=cargo_payload([{"GameId": "g1", "Team1Pick1": "Azir"}]))
    if tables.startswith("ScoreboardPlayers"):
        rows = [{"GameId": "g1", "Name": f"p{i}"} for i in range(3)]
        offset = int(request.url.params["offset"])
        return httpx.Response(200, json=cargo_payload(rows[offset : offset + 2]))
    return httpx.Response(400)


def test_tournaments_query_quotes_and_filters():
    q = leaguepedia.tournaments_query(2026, ["LoL Champions Korea", 'Weird "League"'])
    assert "T.Year = 2026" in q.where
    assert '"LoL Champions Korea"' in q.where
    assert '\\"League\\"' in q.where  # comillas escapadas


@respx.mock
def test_ingest_year_writes_raw_files(settings):
    respx.get(API).mock(side_effect=route_by_table)

    summary = leaguepedia.ingest_year(2026, settings, skip_finished=False)

    assert summary == {TOURNAMENT["OverviewPage"]: {"games": 1, "draft": 1, "players": 3}}
    store = RawStore(settings)
    uri = store.uri("leaguepedia", "players", "year=2026", "lck_2026_season_rounds_1_2.json")
    doc = store.read_json(uri)
    assert doc["row_count"] == 3
    assert doc["table"] == "ScoreboardPlayers"
    assert "OverviewPage" in doc["query"]["where"]


@respx.mock
def test_rerun_is_idempotent(settings):
    respx.get(API).mock(side_effect=route_by_table)
    leaguepedia.ingest_year(2026, settings, skip_finished=False)
    leaguepedia.ingest_year(2026, settings, skip_finished=False)

    store = RawStore(settings)
    files = store.fs.glob(store.fs._strip_protocol(store.uri("leaguepedia", "**", "*.json")))
    assert len(files) == 4  # tournaments + games + draft + players, sin duplicados
    assert not [f for f in files if f.endswith(".tmp")]


@respx.mock
def test_skips_finished_tournament_already_ingested(settings):
    route = respx.get(API).mock(side_effect=route_by_table)
    old = {**TOURNAMENT, "Date": (date.today() - timedelta(days=30)).isoformat()}

    leaguepedia.ingest_tournament(old, settings, skip_finished=True)
    calls_first = route.call_count
    counts = leaguepedia.ingest_tournament(old, settings, skip_finished=True)

    assert route.call_count == calls_first  # no volvió a llamar a la API
    assert counts == {"games": -1, "draft": -1, "players": -1}


def test_slug_is_stable():
    from lolpro.storage import slugify

    assert slugify("LCK/2026 Season/Rounds 1-2") == "lck_2026_season_rounds_1_2"
    assert slugify("Worlds Ñandú") == "worlds_nandu"
