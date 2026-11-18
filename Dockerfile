# Imagen de Airflow extendida con el paquete del proyecto (lolpro).
FROM apache/airflow:3.4.0

USER airflow
COPY --chown=airflow:root pyproject.toml README.md /opt/lolpro/
COPY --chown=airflow:root src /opt/lolpro/src

# Fijamos la versión de Airflow para que pip no la actualice al instalar dependencias.
RUN pip install --no-cache-dir "apache-airflow==${AIRFLOW_VERSION}" /opt/lolpro
