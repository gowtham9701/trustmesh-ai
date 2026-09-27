FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    APP_ENV=development \
    TRUSTMESH_PUBLIC_MODE=true \
    DATA_DIR=/app/data \
    DATABASE_PATH=/tmp/trustmesh/trustmesh.sqlite3 \
    VECTOR_INDEX_DIR=/tmp/trustmesh/vector-index

WORKDIR /app
COPY backend/requirements.txt /app/backend-requirements.txt
COPY frontend/requirements.txt /app/frontend-requirements.txt
RUN pip install --no-cache-dir -r /app/backend-requirements.txt -r /app/frontend-requirements.txt \
    && useradd --create-home --uid 10001 trustmesh \
    && mkdir -p /tmp/trustmesh \
    && chown -R trustmesh:trustmesh /tmp/trustmesh

COPY backend /app/backend
COPY frontend /app/frontend
COPY data /app/data
COPY .streamlit /app/.streamlit

USER 10001
EXPOSE 8080
CMD ["python", "-m", "backend.app.combined_server"]
