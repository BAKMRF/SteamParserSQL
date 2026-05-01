from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator
from airflow.operators.python import PythonOperator
from airflow.providers.postgres.operators.postgres import PostgresOperator

default_args = {
    'owner': 'steam_parser',
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

with DAG(
    dag_id='steam_parser_dag',
    default_args=default_args,
    description='Parse Steam accounts - Bash + Python + Postgres',
    schedule_interval='0 */6 * * *',
    start_date=datetime(2026, 5, 1),
    catchup=False,
    tags=['steam'],
) as dag:

    # 1. BashOperator — проверка окружения
    t1_bash = BashOperator(
        task_id='check_environment',
        bash_command='echo "API Key: ${STEAM_API_KEY:0:4}**** | DB Host: $DB_HOST"',
    )

    # 2. PythonOperator — парсинг
    def run_parser(**context):
        import sys
        sys.path.insert(0, '/opt/airflow')
        from parser import run_parser as do_parse
        session_id, successful, failed = do_parse()
        print(f"Session: {session_id}, OK: {successful}, Failed: {failed}")
        if failed > 0:
            raise ValueError(f"Failed profiles: {failed}")
        return session_id

    t2_python = PythonOperator(
        task_id='parse_steam_profiles',
        python_callable=run_parser,
    )

    # 3. PostgresOperator — проверка результата в БД
    t3_postgres = PostgresOperator(
        task_id='verify_database',
        postgres_conn_id='steam_parser_db',
        sql="""
            SELECT 'Sessions: ' || COUNT(*) 
            FROM parse_sessions 
            WHERE status = 'success';
        """,
        autocommit=True,
    )

    t1_bash >> t2_python >> t3_postgres