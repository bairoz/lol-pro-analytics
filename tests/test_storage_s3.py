"""Prueba la escritura en un S3 'falso' (moto), igual que lo haría con SeaweedFS o AWS."""

import pytest

moto_server = pytest.importorskip("moto.server")

from lolpro.config import Settings  # noqa: E402
from lolpro.storage import RawStore, envelope  # noqa: E402


@pytest.fixture(scope="module")
def s3_endpoint():
    server = moto_server.ThreadedMotoServer(port=0)
    server.start()
    host, port = server.get_host_and_port()
    yield f"http://{host}:{port}"
    server.stop()


def test_write_and_read_on_s3(s3_endpoint, monkeypatch):
    monkeypatch.setenv("AWS_DEFAULT_REGION", "us-east-1")
    settings = Settings(
        RAW_BASE_URI="s3://lol-raw",
        S3_ENDPOINT_URL=s3_endpoint,
        AWS_ACCESS_KEY_ID="test",
        AWS_SECRET_ACCESS_KEY="test",
    )
    store = RawStore(settings)  # crea el bucket si no existe
    uri = store.uri("leaguepedia", "games", "year=2026", "x.json")

    store.write_json(uri, envelope("leaguepedia", "ScoreboardGames", {}, [{"GameId": "g1"}]))

    assert store.exists(uri)
    assert store.read_json(uri)["rows"] == [{"GameId": "g1"}]
