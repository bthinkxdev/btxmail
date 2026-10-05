.PHONY: help dev-backend dev-frontend test lint build up down logs migrate shell createsuperuser check-mailcow

help:
	@echo "dev-backend     Run Django on :8000 with SQLite (DEBUG)"
	@echo "dev-frontend    Run Vite on :5173, proxying /api to :8000"
	@echo "test            Backend tests + frontend type-check and build"
	@echo "lint            ruff lint/format check"
	@echo "up / down       Start / stop the production stack (docker compose)"
	@echo "logs            Follow container logs"
	@echo "migrate         Apply database migrations in the running stack"
	@echo "check-mailcow   Verify the Mailcow API connection from the stack"

dev-backend:
	cd backend && DJANGO_DEBUG=1 CELERY_TASK_ALWAYS_EAGER=1 ENFORCE_2FA=0 python manage.py migrate && \
	DJANGO_DEBUG=1 CELERY_TASK_ALWAYS_EAGER=1 ENFORCE_2FA=0 python manage.py bootstrap && \
	DJANGO_DEBUG=1 CELERY_TASK_ALWAYS_EAGER=1 ENFORCE_2FA=0 python manage.py runserver 127.0.0.1:8000

dev-frontend:
	cd frontend && npm run dev

test:
	cd backend && python -m pytest
	cd frontend && npm run build

lint:
	cd backend && ruff check . && ruff format --check .

build:
	docker compose build

up:
	docker compose up -d --build

down:
	docker compose down

logs:
	docker compose logs -f --tail=200

migrate:
	docker compose exec backend python manage.py migrate

shell:
	docker compose exec backend python manage.py shell

createsuperuser:
	docker compose exec backend python manage.py createsuperuser

check-mailcow:
	docker compose exec backend python manage.py check_mailcow
