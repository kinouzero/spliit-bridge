FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

RUN groupadd --system app \
    && useradd --system \
        --gid app \
        --home-dir /app \
        --create-home \
        app

COPY --chown=app:app app/ /app/
COPY --chown=app:app config.json /app/config.json

USER app

EXPOSE 8787

CMD ["python", "-u", "/app/server.py"]