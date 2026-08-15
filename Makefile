# Единая точка входа для операций проекта.
# Зависимости ставятся только через uv — не pip и не poetry.

.DEFAULT_GOAL := help
COMPOSE ?= docker compose

DC_LOCAL      := $(COMPOSE) --env-file .env -f docker/docker-compose.local.yml
DC_PROD_CADDY := $(COMPOSE) --env-file .env -f docker/docker-compose.prod.caddyfile.yml
DC_PROD_NGINX := $(COMPOSE) --env-file .env -f docker/docker-compose.prod.nginx.yml

.PHONY: help install run lint format test check \
        migrate migration \
        up-local down-local logs \
        up-prod-caddy down-prod-caddy up-prod-nginx down-prod-nginx \
        clean

help: ## Показать список целей
	@grep -E '^[a-zA-Z_-]+:.*## ' $(MAKEFILE_LIST) \
	  | awk 'BEGIN {FS = ":.*## "}; {printf "  \033[36m%-16s\033[0m %s\n", $$1, $$2}'

# --- Разработка ---------------------------------------------------------------

install: ## Установить зависимости
	uv sync

run: ## Запустить бота локально (polling, без вебхука)
	MODE=polling uv run python -m bot

lint: ## Проверить код линтером
	uv run ruff check .

format: ## Отформатировать код
	uv run ruff format .

test: ## Прогнать тесты (нужен запущенный postgres)
	uv run pytest

check: lint test ## Полная проверка перед коммитом

# --- База данных ----------------------------------------------------------------

migrate: ## Применить миграции БД
	uv run alembic upgrade head

migration: ## Сгенерировать новую миграцию: make migration m="описание"
	@test -n "$(m)" || { echo "Укажите описание: make migration m=\"добавил users\""; exit 1; }
	uv run alembic revision --autogenerate -m "$(m)"

# --- Docker -----------------------------------------------------------------------
# --env-file .env обязателен: без него Compose ищет .env рядом с самим
# compose-файлом (в docker/), и подстановка ${PORT} в ports: молча берёт
# дефолт.
#
# Прод-стек существует в двух вариантах фронта — за Caddy и за Nginx,
# поэтому у него два независимых набора целей вместо одного up-prod/down-prod.

up-local: ## Поднять бота и postgres локально в docker
	$(DC_LOCAL) up -d --build

down-local: ## Остановить локальный docker-стек
	$(DC_LOCAL) down

logs: ## Логи локального стека (follow)
	$(DC_LOCAL) logs -f bot

up-prod-caddy: ## Поднять прод-стек за Caddy
	$(DC_PROD_CADDY) up -d

down-prod-caddy: ## Остановить прод-стек за Caddy
	$(DC_PROD_CADDY) down

up-prod-nginx: ## Поднять прод-стек за Nginx
	$(DC_PROD_NGINX) up -d

down-prod-nginx: ## Остановить прод-стек за Nginx
	$(DC_PROD_NGINX) down

# --- Прочее -------------------------------------------------------------------------

clean: ## Удалить кэши и временные артефакты
	find . -type d -name __pycache__ -prune -exec rm -rf {} +
	rm -rf .pytest_cache .ruff_cache .coverage htmlcov
