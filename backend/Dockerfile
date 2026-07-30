FROM python:3.11.9-slim
WORKDIR /app
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1
COPY backend/requirements.lock .
RUN pip install --no-cache-dir -r requirements.lock
COPY backend/ .
COPY scenarios/ /app/scenarios/
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
