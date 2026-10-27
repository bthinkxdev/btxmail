#!/bin/sh
# Container entrypoint. Roles: web | worker | beat | manage <args>
set -eu

wait_for_db() {
  python - <<'PY'
import os, sys, time
import django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "config.settings")
django.setup()
from django.db import connection
for attempt in range(60):
    try:
        connection.ensure_connection()
        sys.exit(0)
    except Exception as exc:  # noqa: BLE001
        print(f"waiting for database ({exc.__class__.__name__})…", flush=True)
        time.sleep(2)
print("database not reachable", flush=True)
sys.exit(1)
PY
}

role="${1:-web}"
shift || true

case "$role" in
  web)
    wait_for_db
    if [ "${RUN_MIGRATIONS:-1}" = "1" ]; then
      python manage.py migrate --noinput
      python manage.py bootstrap
    fi
    exec gunicorn config.wsgi:application \
      --bind 0.0.0.0:8000 \
      --workers "${GUNICORN_WORKERS:-3}" \
      --threads "${GUNICORN_THREADS:-4}" \
      --worker-class gthread \
      --timeout "${GUNICORN_TIMEOUT:-60}" \
      --graceful-timeout 30 \
      --max-requests 2000 --max-requests-jitter 200 \
      --forwarded-allow-ips "${GUNICORN_FORWARDED_ALLOW_IPS:-*}" \
      --access-logfile - --error-logfile -
    ;;
  worker)
    wait_for_db
    exec celery -A config worker --loglevel "${LOG_LEVEL:-INFO}" --concurrency "${CELERY_CONCURRENCY:-4}" \
      --max-tasks-per-child 500 -Q default
    ;;
  beat)
    wait_for_db
    exec celery -A config beat --loglevel "${LOG_LEVEL:-INFO}" --schedule /tmp/celerybeat-schedule --pidfile=
    ;;
  manage)
    exec python manage.py "$@"
    ;;
  *)
    exec "$role" "$@"
    ;;
esac
