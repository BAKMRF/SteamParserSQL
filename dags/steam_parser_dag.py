from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'steam_parser',
    'retries': 2,
    'retry_delay': timedelta(minutes=5),
}

with DAG(
    dag_id='steam_parser_dag',
    default_args=default_args,
    description='Parse Steam accounts and save to PostgreSQL',
    schedule_interval='0 */6 * * *',  # Каждые 6 часов
    start_date=datetime(2026, 5, 1),
    catchup=False,
    tags=['steam'],
) as dag:

    parse_task = BashOperator(
        task_id='run_steam_parser',
        bash_command='cd /opt/airflow && python parser.py',
    )

    parse_task
