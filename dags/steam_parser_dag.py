from datetime import datetime, timedelta
from airflow import DAG
from airflow.operators.bash import BashOperator

default_args = {
    'owner': 'steam_parser',
    'retries': 1,
    'retry_delay': timedelta(minutes=2),
}

with DAG(
    dag_id='steam_parser_dag',
    default_args=default_args,
    description='Parse Steam accounts',
    schedule_interval='0 */6 * * *',
    start_date=datetime(2026, 5, 1),
    catchup=False,
    tags=['steam'],
) as dag:

    t1_check_env = BashOperator(
        task_id='check_environment',
        bash_command='echo "API Key: ${STEAM_API_KEY:0:4}**** | DB: $DB_HOST"',
    )

    t2_parse = BashOperator(
        task_id='parse_steam_profiles',
        bash_command='cd /opt/airflow && python parser.py',
    )

    t3_check_db = BashOperator(
        task_id='verify_database',
        bash_command='python /opt/airflow/check_db.py',
    )

    t1_check_env >> t2_parse >> t3_check_db
