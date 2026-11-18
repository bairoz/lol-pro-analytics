"""Configuración central del proyecto.

Todo se lee desde variables de entorno (o un archivo .env), así el mismo código
corre en tu máquina, dentro de Airflow o en CI sin cambios.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Almacenamiento crudo (capa raw / bronze) ---
    # "file://data/raw" para disco local, "s3://lol-raw" para SeaweedFS / S3.
    raw_base_uri: str = Field(default="file://data/raw", alias="RAW_BASE_URI")
    s3_endpoint_url: str | None = Field(default=None, alias="S3_ENDPOINT_URL")
    aws_access_key_id: str | None = Field(default=None, alias="AWS_ACCESS_KEY_ID")
    aws_secret_access_key: str | None = Field(default=None, alias="AWS_SECRET_ACCESS_KEY")

    # --- Leaguepedia ---
    leaguepedia_api_url: str = Field(
        default="https://lol.fandom.com/api.php", alias="LEAGUEPEDIA_API_URL"
    )
    # Fandom pide un User-Agent que identifique tu proyecto y cómo contactarte.
    user_agent: str = Field(
        default="lol-pro-analytics/0.1 (proyecto de portafolio; contacto: tu-email@ejemplo.com)",
        alias="LOLPRO_USER_AGENT",
    )
    # Segundos mínimos entre peticiones. Leaguepedia limita a usuarios anónimos:
    # mejor ir lento y seguro que recibir errores "ratelimited".
    leaguepedia_min_interval_s: float = Field(default=2.0, alias="LEAGUEPEDIA_MIN_INTERVAL_S")
    # Máximo de filas por petición que Cargo permite a usuarios anónimos.
    leaguepedia_page_size: int = Field(default=500, alias="LEAGUEPEDIA_PAGE_SIZE")

    # Ligas a ingerir (valor exacto de Tournaments.League en Leaguepedia).
    # Verifica los nombres con:  lolpro list-leagues --year 2026
    leagues: list[str] = Field(
        default=[
            "LoL Champions Korea",
            "Tencent LoL Pro League",
            "LoL EMEA Championship",
            "League of Legends Championship Series",
            "Circuit Brazilian League of Legends",
            "Mid-Season Invitational",
            "World Championship",
        ],
        alias="LOLPRO_LEAGUES",
    )

    def storage_options(self) -> dict:
        """Opciones para fsspec/s3fs cuando el destino es S3-compatible."""
        if not self.raw_base_uri.startswith("s3://"):
            return {}
        opts: dict = {}
        if self.aws_access_key_id:
            opts["key"] = self.aws_access_key_id
            opts["secret"] = self.aws_secret_access_key
        if self.s3_endpoint_url:
            opts["client_kwargs"] = {"endpoint_url": self.s3_endpoint_url}
        return opts


@lru_cache
def get_settings() -> Settings:
    return Settings()
