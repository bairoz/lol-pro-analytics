# LoL Pro Analytics 🏆

Pipeline de datos de **esports profesionales de League of Legends** (LCK, LPL, LEC, LCS, CBLOL, MSI y Worlds)
para responder tres preguntas:

1. **Draft:** ¿qué campeones se priorizan, importa el lado azul o el first pick, cómo cambia por parche?
2. **Juego temprano:** ¿cuánto predice la ventaja al minuto 15 el resultado? ¿qué objetivo temprano pesa más?
3. **Estilos por región:** ¿China juega más rápido? ¿Europa más "de libro"? ¿Corea convierte mejor sus ventajas?

> Proyecto de portafolio de Data Engineering. Estado actual: **fase 1, ingesta**.

## Arquitectura

```
Leaguepedia (Cargo API) ─┐
GRID Open Access (*) ────┤──►  Python (ingesta)  ──►  SeaweedFS / S3  (raw, JSON)
                         │                                │
                         │                       DuckDB + dbt (*)   bronze → silver → gold
                         │                                │
                         └──── orquestado por Airflow ────┴──►  Streamlit (*)

(*) próximas fases
```

| Capa | Herramienta | Decisión |
|---|---|---|
| Ingesta | Python, httpx, tenacity | Paginación, rate limiting propio y reintentos con backoff exponencial |
| Raw | SeaweedFS (S3-compatible) vía fsspec | El mismo código escribe en S3 real cambiando una variable. Se eligió SeaweedFS porque MinIO Community fue archivado en 2026 |
| Orquestación | Airflow 3 (LocalExecutor) | Mapeo dinámico: una tarea por torneo; sin Celery ni Redis para ahorrar RAM |
| Calidad | pytest, ruff, pre-commit, GitHub Actions | Tests con APIs simuladas (respx) y S3 simulado (moto) |

### Decisiones de ingeniería

- **Idempotencia:** cada torneo se guarda en una ruta determinística
  `raw/leaguepedia/<tabla>/year=<año>/<torneo>.json`. Re-ejecutar sobrescribe en lugar de duplicar.
- **Carga incremental:** los torneos terminados hace más de 7 días y ya ingeridos se saltan
  (`--full-refresh` para forzar).
- **Linaje:** cada archivo raw guarda la consulta exacta, la fecha de ingesta y el número de filas.
- **Respeto a la fuente:** máximo una petición cada 2 s y un User-Agent identificable.
- **Escrituras atómicas:** en disco local se escribe a un temporal y se renombra.

## Datos que se ingieren (fase 1)

| Archivo raw | Tabla Cargo | Grano |
|---|---|---|
| `tournaments` | `Tournaments` | 1 fila por torneo |
| `games` | `ScoreboardGames` | 1 fila por partida (Team1 = lado azul) |
| `draft` | `PicksAndBansS7` | 1 fila por partida, con bans/picks en orden y roles |
| `players` | `ScoreboardPlayers` | 1 fila por jugador por partida |

---

## Instalación en Windows 11

Todo corre dentro de **WSL2** (Linux en Windows). Es como se trabaja en la industria y evita problemas
de rutas y permisos con Docker.

### 1. WSL2 + Ubuntu
En PowerShell **como administrador**:
```powershell
wsl --install -d Ubuntu
```
Reinicia y crea tu usuario de Ubuntu cuando lo pida.

### 2. Docker Desktop
Instala [Docker Desktop](https://www.docker.com/products/docker-desktop/), y en
*Settings → Resources → WSL integration* activa **Ubuntu**.
Con 16 GB de RAM, WSL2 usa hasta 8 GB por defecto: alcanza para este proyecto.

### 3. Herramientas (dentro de Ubuntu)
```bash
sudo apt update && sudo apt install -y git
curl -LsSf https://astral.sh/uv/install.sh | sh    # gestor de Python
```
Recomendado: VS Code con la extensión **WSL** (abre el proyecto con `code .` desde Ubuntu).

### 4. Clonar el proyecto
> ⚠️ Clónalo dentro de Linux (`~/projects`), **no** en `/mnt/c/...`: es mucho más rápido y evita
> problemas de permisos.
```bash
mkdir -p ~/projects && cd ~/projects
git clone https://github.com/bairoz/lol-pro-analytics.git
cd lol-pro-analytics
cp .env.example .env      # y edita LOLPRO_USER_AGENT con tu correo o GitHub
```

---

## Uso

### Opción A: sin Docker (ideal para desarrollar)
```bash
uv sync                                     # crea .venv e instala todo
uv run pytest                               # corre los tests
uv run lolpro list-leagues --year 2026      # nombres exactos de las ligas en Leaguepedia
uv run lolpro tournaments --year 2026       # lista de torneos que se van a ingerir
uv run lolpro ingest --year 2026 --tournament "<OverviewPage de un torneo>"   # prueba con uno
uv run lolpro ingest --year 2026            # todos
```
Los archivos quedan en `data/raw/leaguepedia/...`.

### Opción B: con Airflow + SeaweedFS
```bash
docker compose build
docker compose up airflow-init              # solo la primera vez (crea la BD y el usuario)
docker compose up -d
```
- Airflow: <http://localhost:8080> (usuario `airflow`, contraseña `airflow`)
- Archivos raw: <http://localhost:8888/buckets/lol-raw/>

En Airflow, activa el DAG **`leaguepedia_ingest`** y ejecútalo con *Trigger* (puedes elegir el año).
Verás una tarea por torneo, con el nombre del torneo en la UI.

Para apagar todo: `docker compose down` (añade `-v` para borrar también los datos).

### Primer arranque: verifica la configuración
1. `uv run lolpro list-leagues --year 2026`: compara los nombres con `LOLPRO_LEAGUES` en
   `src/lolpro/config.py` y ajústalos si alguno no coincide (en 2026 la LTA volvió a separarse en LCS y CBLOL).
2. Si Leaguepedia responde con un error de campo, revisa los campos de cada tabla en
   <https://lol.fandom.com/wiki/Special:CargoTables> y corrige las listas en
   `src/lolpro/ingestion/leaguepedia.py`.

---

## Estructura

```
├── dags/leaguepedia_ingest.py      # DAG de Airflow
├── src/lolpro/
│   ├── config.py                   # configuración por variables de entorno
│   ├── storage.py                  # capa raw: disco local o S3 (fsspec)
│   ├── cli.py                      # comando `lolpro`
│   └── ingestion/
│       ├── cargo_client.py         # cliente de la Cargo API (paginación, reintentos)
│       └── leaguepedia.py          # qué tablas y campos se descargan
├── tests/                          # pytest con API simulada (respx) y S3 simulado (moto)
├── infra/seaweedfs/s3.json         # credenciales locales de SeaweedFS
├── docker-compose.yaml             # Airflow 3 + Postgres + SeaweedFS
└── Dockerfile                      # imagen de Airflow + paquete lolpro
```

## Roadmap

- [x] **Fase 1:** ingesta de Leaguepedia → raw (Airflow, SeaweedFS, tests, CI)
- [ ] **Fase 2:** DuckDB + dbt (staging → marts: `fct_games`, `fct_draft_actions`, `fct_player_games`) + dbt tests
- [ ] **Fase 3:** análisis del draft
- [ ] **Fase 4:** GRID Open Access (datos en partida de Worlds 2026) → juego temprano
- [ ] **Fase 5:** estilos por región + dashboard en Streamlit

## Fuentes de datos y avisos

- [Leaguepedia](https://lol.fandom.com): datos comunitarios bajo licencia CC BY-SA.
- [Riot Games Open Access, powered by GRID](https://grid.gg/riot-open-access/): uso no comercial.
- Los datos de la LPL no los organiza Riot directamente y algunas métricas pueden diferir de las de otras ligas.

*LoL Pro Analytics isn't endorsed by Riot Games and doesn't reflect the views or opinions of Riot Games
or anyone officially involved in producing or managing Riot Games properties. Riot Games, and all
associated properties are trademarks or registered trademarks of Riot Games, Inc.*
