FROM python:3.11.9-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PYTHONPATH=/app
COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ .
COPY scenarios/ /app/scenarios/
COPY scripts/ /app/scripts/
COPY tests/evaluation/ /app/tests/evaluation/
COPY docs/v2/ /app/docs/v2/
COPY docs/ /app/knowledge_sources/docs/
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
