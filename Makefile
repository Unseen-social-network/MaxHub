.PHONY: help install run lint format test migrate migration up-local down-local logs-local up-prod down-prod

help: ## Показать список команд
	@grep -E '^[a-zA-Z_-]+:.*## .*$$' $(MAKEFILE_LIST) | sort | awk 'BEGIN {FS = ":.*## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'

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

migrate: ## Применить миграции БД
	uv run alembic upgrade head

migration: ## Сгенерировать новую миграцию (make migration m="описание")
	uv run alembic revision --autogenerate -m "$(m)"

up-local: ## Поднять бота и postgres локально в docker
	docker compose -f docker/docker-compose.local.yml up -d --build

down-local: ## Остановить локальный docker-стек
	docker compose -f docker/docker-compose.local.yml down

logs-local: ## Логи локального docker-стека
	docker compose -f docker/docker-compose.local.yml logs -f bot

up-prod: ## Поднять прод-стек (bot, postgres, caddy)
	docker compose -f docker/docker-compose.prod.yml up -d

down-prod: ## Остановить прод-стек
	docker compose -f docker/docker-compose.prod.yml down
