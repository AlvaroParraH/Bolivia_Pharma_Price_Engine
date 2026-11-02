FROM ghcr.io/astral-sh/uv:0.9.8 AS uv
FROM apache/airflow:3.3.2

USER root
COPY --from=uv /uv /usr/local/bin/uv
RUN apt-get update \
    && apt-get install -y --no-install-recommends xvfb x11vnc novnc websockify x11-utils \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

ENV UV_PROJECT_ENVIRONMENT=/opt/pharma/.venv \
    UV_PYTHON_DOWNLOADS=never \
    PLAYWRIGHT_BROWSERS_PATH=/opt/playwright
WORKDIR /opt/pharma
COPY pyproject.toml uv.lock ./
RUN uv sync --locked --no-dev --no-install-project \
    && /opt/pharma/.venv/bin/python -m playwright install --with-deps chromium \
    && chmod -R a+rX /opt/pharma /opt/playwright
COPY pipelines/ingestion /opt/pharma/pipelines/ingestion
COPY pipelines/orchestration/airflow/browser-desktop.sh /opt/pharma/browser-desktop.sh
USER airflow
WORKDIR /opt/airflow
