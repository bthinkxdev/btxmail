# syntax=docker/dockerfile:1.7
FROM python:3.12-slim-bookworm AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

RUN apt-get update \
 && apt-get install -y --no-install-recommends libpq5 tini \
 && rm -rf /var/lib/apt/lists/* \
 && groupadd --system --gid 10001 app \
 && useradd --system --uid 10001 --gid app --home-dir /app --shell /usr/sbin/nologin app

WORKDIR /app
COPY requirements/base.txt requirements/base.txt
RUN pip install -r requirements/base.txt

COPY --chown=app:app . .
# collectstatic with production storage so the hashed manifest exists at runtime
RUN DJANGO_DEBUG=0 \
    DJANGO_SECRET_KEY=build-only-not-secret-build-only-not-secret-build-only-not-secret \
    DJANGO_ALLOWED_HOSTS=build.invalid \
    DATABASE_URL=sqlite:////tmp/build.sqlite3 \
    FIELD_ENCRYPTION_KEY=build-only USE_LOCMEM_CACHE=1 \
    python manage.py collectstatic --noinput \
 && chmod +x docker/entrypoint.sh

USER app
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=30s --retries=3 \
  CMD python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=4).status==200 else 1)" || exit 1

ENTRYPOINT ["/usr/bin/tini", "--", "/app/docker/entrypoint.sh"]
CMD ["web"]
