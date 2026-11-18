import pytest
from tenacity import wait_none

from lolpro.config import Settings
from lolpro.ingestion.cargo_client import CargoClient

API = "https://lol.test/api.php"


@pytest.fixture(autouse=True)
def no_retry_wait():
    """En tests no queremos esperar los segundos del backoff."""
    original = CargoClient._get_page.retry.wait
    CargoClient._get_page.retry.wait = wait_none()
    yield
    CargoClient._get_page.retry.wait = original


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        RAW_BASE_URI=f"file://{tmp_path}/raw",
        LEAGUEPEDIA_API_URL=API,
        LEAGUEPEDIA_MIN_INTERVAL_S=0,
        LEAGUEPEDIA_PAGE_SIZE=2,
        LOLPRO_LEAGUES=["LoL Champions Korea"],
    )


def cargo_payload(rows: list[dict]) -> dict:
    return {"cargoquery": [{"title": r} for r in rows]}
