"""DAG: ingesta semanal de Leaguepedia a la capa raw (SeaweedFS / S3).

  get_tournaments ──► ingest_tournament (una tarea por torneo, mapeo dinámico)

- Mapeo dinámico: Airflow crea una tarea por torneo en tiempo de ejecución,
  así un fallo en un torneo no obliga a repetir los demás.
- max_active_tis_per_dag=1: los torneos se procesan de uno en uno para respetar
  el límite de peticiones de Leaguepedia.
- Idempotente: re-ejecutar sobrescribe los mismos archivos.
"""

from __future__ import annotations

from datetime import datetime, timedelta

from airflow.sdk import Param, dag, get_current_context, task


@dag(
    dag_id="leaguepedia_ingest",
    description="Torneos, partidas, draft y jugadores de Leaguepedia → raw",
    schedule="0 6 * * 1",  # lunes 06:00 UTC, tras los partidos del fin de semana
    start_date=datetime(2026, 1, 1),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=5)},
    params={
        "year": Param(datetime.now().year, type="integer", description="Temporada a ingerir"),
        "full_refresh": Param(False, type="boolean", description="Re-descargar torneos terminados"),
    },
    tags=["ingestion", "leaguepedia", "raw"],
)
def leaguepedia_ingest():
    @task
    def get_tournaments() -> list[dict]:
        from lolpro.ingestion import leaguepedia

        params = get_current_context()["params"]
        return leaguepedia.get_tournaments(int(params["year"]))

    # map_index_template: en la UI cada tarea se ve con el nombre del torneo, no como 0, 1, 2...
    @task(max_active_tis_per_dag=1, map_index_template="{{ tournament_name }}")
    def ingest_tournament(tournament: dict) -> dict[str, int]:
        from lolpro.ingestion import leaguepedia

        context = get_current_context()
        context["tournament_name"] = tournament["OverviewPage"]
        params = context["params"]
        return leaguepedia.ingest_tournament(tournament, skip_finished=not params["full_refresh"])

    ingest_tournament.expand(tournament=get_tournaments())


leaguepedia_ingest()
