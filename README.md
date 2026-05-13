# 🎮 Steam Parser & Analytics System

Система для сбора, хранения и анализа данных Steam-аккаунтов с оркестрацией через Apache Airflow.

## 📊 Архитектура
```
┌─────────────────┐ ┌──────────────────┐ ┌─────────────────┐
│ Steam API │───▶│ Apache Airflow │───▶│ PostgreSQL │
│ (внешний мир) │ │ (оркестрация) │ │ (хранение) │
└─────────────────┘ └──────────────────┘ └─────────────────┘
│ │
▼ ▼
┌──────────────┐ ┌──────────────┐
│ Веб-интерфейс│ │ Streamlit │
│ Airflow UI │ │ Дашборд │
│ :8081 │ │ :8501 │
└──────────────┘ └──────────────┘
```
## 🛠 Стек технологий

- **Python 3.10+** — парсер, дашборд
- **PostgreSQL 15** — хранение данных
- **Apache Airflow 2.9** — оркестрация и расписание
- **Streamlit** — веб-интерфейс аналитики
- **Docker / Docker Compose** — контейнеризация
- **GitHub Actions** — CI/CD

## 📦 Структура проекта
```
SteamParserSQL/
├── .github/workflows/deploy.yml # CI/CD: тесты + деплой
├── dags/
│ └── steam_parser_dag.py # Airflow DAG (расписание парсинга)
├── parser.py # Модуль парсера (БД + Steam API)
├── app.py # Streamlit дашборд
├── docker-compose.yml # PostgreSQL + Airflow
├── init.sql # Схема БД
├── requirements.txt # Python зависимости
├── .env # Переменные окружения
└── README.md
```
## 🚀 Быстрый старт

### Требования
- Docker и Docker Compose
- Python 3.10+ (для локальной разработки)
- Steam API ключ

### Установка
## 🚀 Установка на чистый Ubuntu

sudo apt install git -y

curl -fsSL https://get.docker.com | sudo sh

sudo usermod -aG docker $USER

newgrp docker

git clone https://github.com/BAKMRF/SteamParserSQL.git

cd SteamParserSQL

nano .env

mkdir -p ./logs/scheduler

chmod -R 777 ./logs

docker compose up -d

sudo apt install python3-venv python3-pip -y

python3 -m venv .venv

source .venv/bin/activate

pip install -r requirements.txt

nohup streamlit run app.py --server.port 8501 --server.address 0.0.0.0 > streamlit.log 2>&1 &

sudo ufw allow 8081

sudo ufw allow 8501

# .env содержимое:
# DB_HOST=127.0.0.1
# DB_PORT=5433
# DB_NAME=steam_parser
# DB_USER=steam_user
# DB_PASSWORD=steam_password
# STEAM_API_KEY=твой_ключ

# Airflow: http://твой-ip:8081 (admin/admin)
# Admin → Connections → + :
# Connection Id: steam_parser_db
# Connection Type: Postgres
# Host: postgres
# Schema: steam_parser
# Login: steam_user
# Password: steam_password
# Port: 5432
# Сохранить

## ⚙️ Airflow DAG

DAG состоит из трёх шагов:

| Задача | Оператор | Описание |
|--------|----------|----------|
| `check_environment` | BashOperator | Проверка переменных окружения |
| `parse_steam_profiles` | PythonOperator | Парсинг Steam аккаунтов |
| `verify_database` | PostgresOperator | Проверка записи в БД |

📅 Расписание парсинга
Airflow DAG запускается каждые 6 часов (0 */6 * * *).

Можно запустить вручную: Airflow UI → Play ▶️ → Trigger DAG.

🔄 CI/CD
При каждом пуше в main:

GitHub Actions проверяет синтаксис app.py и parser.py

Устанавливает зависимости

Деплоит на сервер

Перезапускает Streamlit и Airflow

📊 Возможности
Парсинг Steam аккаунтов через Steam Web API

Сохранение в PostgreSQL (история изменений)

Дашборд на Streamlit с графиками Plotly

Оркестрация через Apache Airflow

Автоматический деплой через CI/CD

Docker-контейнеризация всех сервисов

🗄 Схема БД
parse_sessions — сессии парсинга

profiles — профили Steam

profile_snapshots — снимки данных (история)