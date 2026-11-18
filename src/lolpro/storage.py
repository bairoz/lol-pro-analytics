"""Escritura de la capa raw (bronze) sobre disco local o S3-compatible (SeaweedFS, AWS S3...).

Usamos fsspec: el mismo código escribe en "file://data/raw/..." o en "s3://lol-raw/..."
solo cambiando RAW_BASE_URI. En la nube real bastaría con apuntar a un bucket de S3.
"""

from __future__ import annotations

import json
import re
import unicodedata
from datetime import datetime, timezone
from typing import Any

import fsspec

from lolpro.config import Settings, get_settings


def slugify(value: str) -> str:
    """'LCK/2026 Season/Rounds 1-2' -> 'lck_2026_season_rounds_1_2'."""
    value = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode()
    value = re.sub(r"[^a-zA-Z0-9]+", "_", value).strip("_").lower()
    return value or "unnamed"


class RawStore:
    def __init__(self, settings: Settings | None = None) -> None:
        self.settings = settings or get_settings()
        self.base = self.settings.raw_base_uri.rstrip("/")
        self.fs, _ = fsspec.core.url_to_fs(self.base, **self.settings.storage_options())
        self._ensure_base()

    def _ensure_base(self) -> None:
        # En S3 esto crea el bucket si no existe; en local, la carpeta.
        root = self.fs._strip_protocol(self.base)
        if not self.fs.exists(root):
            self.fs.mkdir(root)

    def uri(self, *parts: str) -> str:
        return "/".join([self.base, *parts])

    def exists(self, uri: str) -> bool:
        return self.fs.exists(uri)

    def write_json(self, uri: str, payload: Any) -> None:
        """Escribe un JSON completo. Sobrescribir la misma ruta hace la carga idempotente."""
        data = json.dumps(payload, ensure_ascii=False, indent=None).encode("utf-8")
        if self.base.startswith("file://") or "://" not in self.base:
            # En disco local: escribir a un temporal y renombrar (nunca queda un archivo a medias).
            tmp = uri + ".tmp"
            self.fs.makedirs(self.fs._parent(uri), exist_ok=True)
            self.fs.pipe_file(tmp, data)
            self.fs.mv(tmp, uri)
        else:
            # Un PUT en S3 ya es atómico.
            self.fs.pipe_file(uri, data)

    def read_json(self, uri: str) -> Any:
        with self.fs.open(uri, "rb") as f:
            return json.load(f)


def envelope(source: str, table: str, params: dict, rows: list[dict]) -> dict:
    """Metadatos de linaje junto a los datos: de dónde vino, con qué consulta y cuándo."""
    return {
        "source": source,
        "table": table,
        "query": params,
        "ingested_at": datetime.now(timezone.utc).isoformat(),
        "row_count": len(rows),
        "rows": rows,
    }
