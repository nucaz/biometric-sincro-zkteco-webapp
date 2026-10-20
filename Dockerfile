# Single image for both the `web` and `sync` services in docker-compose.yml
# -- same dependencies either way, only the command differs. See
# deploy/docker/README.md for how the two containers use it.
FROM python:3.12-slim

# gcc/libpq-dev aren't needed: psycopg2-binary ships a prebuilt wheel for
# this base image's platform, and nothing else in requirements.txt
# compiles from source on a standard manylinux wheel.
WORKDIR /app

COPY central/requirements.txt central/requirements.txt
RUN pip install --no-cache-dir -r central/requirements.txt

COPY . .

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

EXPOSE 5000

# Overridden by the `sync` service in docker-compose.yml -- this default
# is what `web` runs.
CMD ["gunicorn", "--bind", "0.0.0.0:5000", "--workers", "2", "--threads", "8", \
     "--worker-class", "gthread", "--timeout", "300", "central.webapp:app"]
