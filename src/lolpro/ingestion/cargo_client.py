"""Cliente mínimo para la Cargo API de Leaguepedia.

Leaguepedia guarda sus datos en "tablas Cargo" que se consultan con algo muy
parecido a SQL (tables, fields, where, join_on, order_by) a través de api.php.

Este cliente se encarga de lo que hace robusta una ingesta:
  * paginación (limit/offset) hasta traer todas las filas,
  * un intervalo mínimo entre peticiones (rate limiting propio),
  * reintentos con backoff exponencial ante errores de red, 5xx o "ratelimited",
  * normalizar los nombres de campos que devuelve Cargo.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterator
from dataclasses import dataclass

import httpx
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

logger = logging.getLogger(__name__)


class CargoRateLimited(Exception):
    """Leaguepedia respondió que vamos demasiado rápido."""


class CargoQueryError(Exception):
    """Error de la API que no tiene sentido reintentar (consulta mal formada, etc.)."""


@dataclass(frozen=True)
class CargoQuery:
    tables: str
    fields: str
    where: str | None = None
    join_on: str | None = None
    order_by: str | None = None
    group_by: str | None = None

    def to_params(self) -> dict[str, str]:
        params = {"tables": self.tables, "fields": self.fields}
        if self.where:
            params["where"] = self.where
        if self.join_on:
            params["join_on"] = self.join_on
        if self.order_by:
            params["order_by"] = self.order_by
        if self.group_by:
            params["group_by"] = self.group_by
        return params


def normalize_keys(row: dict) -> dict:
    """Cargo devuelve 'DateTime_UTC' como 'DateTime UTC'. Lo dejamos con guion bajo."""
    return {k.replace(" ", "_"): v for k, v in row.items()}


class CargoClient:
    def __init__(
        self,
        api_url: str,
        user_agent: str,
        min_interval_s: float = 2.0,
        page_size: int = 500,
        http_client: httpx.Client | None = None,
    ) -> None:
        self.api_url = api_url
        self.min_interval_s = min_interval_s
        self.page_size = page_size
        self._client = http_client or httpx.Client(
            headers={"User-Agent": user_agent}, timeout=httpx.Timeout(30.0)
        )
        self._last_request_at = 0.0

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> CargoClient:
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    # ------------------------------------------------------------------ #
    def _throttle(self) -> None:
        elapsed = time.monotonic() - self._last_request_at
        if elapsed < self.min_interval_s:
            time.sleep(self.min_interval_s - elapsed)
        self._last_request_at = time.monotonic()

    @retry(
        retry=retry_if_exception_type(
            (httpx.TransportError, httpx.HTTPStatusError, CargoRateLimited)
        ),
        wait=wait_exponential(multiplier=2, min=5, max=120),
        stop=stop_after_attempt(6),
        before_sleep=before_sleep_log(logger, logging.WARNING),
        reraise=True,
    )
    def _get_page(self, params: dict[str, str]) -> list[dict]:
        self._throttle()
        resp = self._client.get(self.api_url, params=params)
        if resp.status_code == 429 or resp.status_code >= 500:
            resp.raise_for_status()
        elif resp.status_code >= 400:
            raise CargoQueryError(f"HTTP {resp.status_code}: {resp.text[:300]}")

        payload = resp.json()
        if "error" in payload:
            code = payload["error"].get("code", "")
            info = payload["error"].get("info", "")
            if code == "ratelimited":
                raise CargoRateLimited(info)
            raise CargoQueryError(f"{code}: {info}")

        return [normalize_keys(item["title"]) for item in payload.get("cargoquery", [])]

    def iter_rows(self, query: CargoQuery) -> Iterator[dict]:
        """Itera sobre todas las filas de la consulta, página por página."""
        offset = 0
        while True:
            params = {
                "action": "cargoquery",
                "format": "json",
                "limit": str(self.page_size),
                "offset": str(offset),
                **query.to_params(),
            }
            rows = self._get_page(params)
            yield from rows
            if len(rows) < self.page_size:
                return
            offset += self.page_size

    def query(self, query: CargoQuery) -> list[dict]:
        return list(self.iter_rows(query))
