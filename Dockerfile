FROM python:3.12-slim@sha256:5e2bdb1b0d542d5039cffb8181c65930093949194a65c365dfb1b0fe13a4fa5b AS app-base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_DEFAULT_TIMEOUT=600 \
    PIP_RETRIES=5

WORKDIR /app

RUN addgroup --system app && adduser --system --ingroup app app

COPY requirements.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements.lock

COPY --chown=app:app app ./app
COPY --chown=app:app alembic.ini ./
COPY --chown=app:app alembic ./alembic


FROM app-base AS test

ENV PYTHONPATH=/app

COPY requirements-dev.lock ./
RUN --mount=type=cache,target=/root/.cache/pip pip install -r requirements-dev.lock
COPY --chown=app:app tests ./tests
COPY --chown=app:app pyproject.toml ./

USER app
CMD ["python", "-m", "pytest", "-W", "error"]


FROM app-base AS runtime

USER app
EXPOSE 8000

CMD ["sh", "-c", "alembic upgrade head && python -m app.startup && uvicorn app.main:app --host 0.0.0.0 --port 8000"]
