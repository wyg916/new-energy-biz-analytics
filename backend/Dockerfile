FROM python:3.11-alpine@sha256:25976e9d34a0fab1f278cae931f34c8303d97bf0c0d7f85b6b4dcf641d7702a4
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY backend/requirements.lock .
RUN python -m pip install --no-cache-dir --upgrade pip==26.2 \
    && python -m pip install --no-cache-dir -r requirements.lock \
    && python -m pip uninstall -y setuptools wheel \
    && python -m pip uninstall -y pip \
    && rm -rf /usr/local/lib/python3.11/ensurepip
COPY backend/ .
COPY scenarios/ /app/scenarios/
COPY scripts/ /app/scripts/
COPY data/open_source/ /app/data/open_source/
COPY tests/evaluation/ /app/tests/evaluation/
COPY docs/v2/ /app/docs/v2/
COPY docs/data/ /app/docs/data/
COPY docs/ /app/knowledge_sources/docs/
COPY integration/knowledge_import_plan.json /app/integration/knowledge_import_plan.json
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
