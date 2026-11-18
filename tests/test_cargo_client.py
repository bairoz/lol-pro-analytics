import httpx
import pytest
import respx

from lolpro.ingestion.cargo_client import CargoClient, CargoQuery, CargoQueryError
from tests.conftest import API, cargo_payload

QUERY = CargoQuery(tables="ScoreboardGames=SG", fields="SG.GameId=GameId")


def make_client(page_size=2) -> CargoClient:
    return CargoClient(api_url=API, user_agent="test", min_interval_s=0, page_size=page_size)


@respx.mock
def test_paginates_until_short_page():
    route = respx.get(API).mock(
        side_effect=[
            httpx.Response(200, json=cargo_payload([{"GameId": "a"}, {"GameId": "b"}])),
            httpx.Response(200, json=cargo_payload([{"GameId": "c"}])),
        ]
    )
    rows = make_client().query(QUERY)

    assert [r["GameId"] for r in rows] == ["a", "b", "c"]
    assert route.call_count == 2
    assert route.calls[1].request.url.params["offset"] == "2"


@respx.mock
def test_normalizes_keys_with_spaces():
    respx.get(API).mock(
        return_value=httpx.Response(200, json=cargo_payload([{"DateTime UTC": "2026-01-01"}]))
    )
    rows = make_client().query(QUERY)
    assert rows == [{"DateTime_UTC": "2026-01-01"}]


@respx.mock
def test_retries_on_ratelimited_then_succeeds():
    route = respx.get(API).mock(
        side_effect=[
            httpx.Response(200, json={"error": {"code": "ratelimited", "info": "slow down"}}),
            httpx.Response(503),
            httpx.Response(200, json=cargo_payload([{"GameId": "a"}])),
        ]
    )
    rows = make_client().query(QUERY)
    assert rows == [{"GameId": "a"}]
    assert route.call_count == 3


@respx.mock
def test_bad_query_fails_fast_without_retry():
    route = respx.get(API).mock(
        return_value=httpx.Response(
            200, json={"error": {"code": "internal_api_error_MWException", "info": "bad field"}}
        )
    )
    with pytest.raises(CargoQueryError):
        make_client().query(QUERY)
    assert route.call_count == 1
