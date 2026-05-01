"""
Модуль парсера Steam аккаунтов.
Используется как для ручного запуска, так и для Airflow DAG.
"""
import os
import re
import time
import requests
from datetime import datetime
from pathlib import Path
from dotenv import load_dotenv
from contextlib import contextmanager
import psycopg2
from psycopg2.extras import RealDictCursor

load_dotenv()

# ==================== КОНФИГУРАЦИЯ ====================

DB_CONFIG = {
    'host': os.getenv('DB_HOST', '127.0.0.1'),
    'port': os.getenv('DB_PORT', '5433'),
    'database': os.getenv('DB_NAME', 'steam_parser'),
    'user': os.getenv('DB_USER', 'steam_user'),
    'password': os.getenv('DB_PASSWORD', 'steam_password')
}

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")

STEAM_ACCOUNTS = [
    'https://steamcommunity.com/profiles/76561199001022272',
    'https://steamcommunity.com/profiles/76561199219594998',
    'https://steamcommunity.com/profiles/76561199384092020',
    'https://steamcommunity.com/profiles/76561198333882340',
    'https://steamcommunity.com/profiles/76561199038225456',
    'https://steamcommunity.com/profiles/76561199082417445',
]

BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
WORD_REPORTS_DIR = DATA_DIR / "word_reports"
DATA_DIR.mkdir(exist_ok=True)
WORD_REPORTS_DIR.mkdir(exist_ok=True)

# ==================== DATABASE MANAGER ====================

class DatabaseManager:
    def __init__(self, config, silent=False):
        self.config = config
        self.silent = silent
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        conn = None
        try:
            conn = psycopg2.connect(**self.config)
            yield conn
        except Exception as e:
            if not self.silent:
                print(f"❌ Ошибка подключения к БД: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    @contextmanager
    def get_cursor(self, cursor_factory=RealDictCursor):
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
                conn.commit()
            except Exception as e:
                conn.rollback()
                if not self.silent:
                    print(f"❌ Ошибка выполнения запроса: {e}")
                raise
            finally:
                cursor.close()
    
    def _init_db(self):
        try:
            with self.get_cursor() as cursor:
                cursor.execute("""
                    SELECT EXISTS (
                        SELECT FROM information_schema.tables 
                        WHERE table_name = 'parse_sessions'
                    );
                """)
                tables_exist = cursor.fetchone()['exists']
                if not tables_exist:
                    if not self.silent:
                        print("🔄 Создание таблиц в базе данных...")
                    self._create_tables()
                else:
                    if not self.silent:
                        print("✅ Подключение к PostgreSQL установлено")
        except Exception as e:
            if not self.silent:
                print(f"❌ Ошибка подключения к PostgreSQL: {e}")
    
    def _create_tables(self):
        create_tables_sql = """
        CREATE TABLE IF NOT EXISTS parse_sessions (
            id SERIAL PRIMARY KEY,
            parse_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            parse_time_display VARCHAR(50),
            timestamp_str VARCHAR(20),
            total_profiles INTEGER DEFAULT 0,
            successful_profiles INTEGER DEFAULT 0,
            failed_profiles INTEGER DEFAULT 0,
            status VARCHAR(20) DEFAULT 'pending'
        );
        CREATE TABLE IF NOT EXISTS profiles (
            id SERIAL PRIMARY KEY,
            steam_id VARCHAR(50) UNIQUE NOT NULL,
            nickname VARCHAR(255),
            country VARCHAR(10),
            avatar_url TEXT,
            steam_level INTEGER DEFAULT 0,
            profile_url TEXT,
            first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            last_updated TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS profile_snapshots (
            id SERIAL PRIMARY KEY,
            session_id INTEGER REFERENCES parse_sessions(id) ON DELETE CASCADE,
            profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
            steam_level INTEGER DEFAULT 0,
            games_count INTEGER DEFAULT 0,
            library_value DECIMAL(10, 2) DEFAULT 0,
            inventory_value DECIMAL(10, 2) DEFAULT 0,
            total_value DECIMAL(10, 2) DEFAULT 0,
            parsed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
            status VARCHAR(20) DEFAULT 'success',
            error_message TEXT,
            UNIQUE(session_id, profile_id)
        );
        CREATE INDEX IF NOT EXISTS idx_parse_sessions_parse_time ON parse_sessions(parse_time);
        CREATE INDEX IF NOT EXISTS idx_profile_snapshots_session_id ON profile_snapshots(session_id);
        CREATE INDEX IF NOT EXISTS idx_profile_snapshots_profile_id ON profile_snapshots(profile_id);
        CREATE INDEX IF NOT EXISTS idx_profiles_steam_id ON profiles(steam_id);
        CREATE INDEX IF NOT EXISTS idx_profiles_last_updated ON profiles(last_updated);
        """
        try:
            with self.get_cursor() as cursor:
                cursor.execute(create_tables_sql)
            if not self.silent:
                print("✅ Таблицы успешно созданы")
        except Exception as e:
            if not self.silent:
                print(f"❌ Ошибка при создании таблиц: {e}")
    
    def create_parse_session(self, parse_time=None):
        if not parse_time:
            parse_time = datetime.now()
        parse_time_display = parse_time.strftime("%d.%m.%Y %H:%M:%S")
        timestamp_str = parse_time.strftime("%Y%m%d_%H%M%S")
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO parse_sessions (parse_time, parse_time_display, timestamp_str, status)
                VALUES (%s, %s, %s, 'pending') RETURNING id
            """, (parse_time, parse_time_display, timestamp_str))
            result = cursor.fetchone()
            return result['id'] if result else None
    
    def update_session_stats(self, session_id, total_profiles, successful, failed):
        with self.get_cursor() as cursor:
            cursor.execute("""
                UPDATE parse_sessions 
                SET total_profiles = %s, successful_profiles = %s, failed_profiles = %s,
                    status = CASE WHEN %s > 0 THEN 'success' ELSE 'failed' END
                WHERE id = %s
            """, (total_profiles, successful, failed, successful, session_id))
    
    def get_or_create_profile(self, steam_id, profile_data):
        with self.get_cursor() as cursor:
            cursor.execute("SELECT id FROM profiles WHERE steam_id = %s", (steam_id,))
            result = cursor.fetchone()
            if result:
                profile_id = result['id']
                cursor.execute("""
                    UPDATE profiles 
                    SET nickname = %s, country = %s, avatar_url = %s, steam_level = %s,
                        profile_url = %s, last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (profile_data.get('nickname'), profile_data.get('country'),
                      profile_data.get('avatar'), profile_data.get('steam_level'),
                      profile_data.get('profile_url'), profile_id))
                return profile_id
            else:
                cursor.execute("""
                    INSERT INTO profiles (steam_id, nickname, country, avatar_url, steam_level, profile_url)
                    VALUES (%s, %s, %s, %s, %s, %s) RETURNING id
                """, (steam_id, profile_data.get('nickname'), profile_data.get('country'),
                      profile_data.get('avatar'), profile_data.get('steam_level'),
                      profile_data.get('profile_url')))
                result = cursor.fetchone()
                return result['id'] if result else None
    
    def save_profile_snapshot(self, session_id, profile_id, profile_data, status='success', error=None):
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO profile_snapshots 
                (session_id, profile_id, steam_level, games_count, library_value, inventory_value, parsed_at, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, profile_id) 
                DO UPDATE SET
                    steam_level = EXCLUDED.steam_level, games_count = EXCLUDED.games_count,
                    library_value = EXCLUDED.library_value, inventory_value = EXCLUDED.inventory_value,
                    parsed_at = EXCLUDED.parsed_at, status = EXCLUDED.status, error_message = EXCLUDED.error_message
            """, (session_id, profile_id, profile_data.get('steam_level', 0),
                  profile_data.get('games_count', 0), profile_data.get('library_value', 0),
                  profile_data.get('inventory_value', 0), profile_data.get('parsed_at', datetime.now()),
                  status, error))
    
    def get_sessions(self, limit=100):
        """Получает список сессий парсинга"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    ps.id as session_id,
                    ps.parse_time,
                    ps.parse_time_display,
                    ps.total_profiles,
                    ps.successful_profiles,
                    ps.failed_profiles,
                    ps.status,
                    COUNT(DISTINCT p.country) as countries_count,
                    COALESCE(SUM(psnap.games_count), 0) as total_games,
                    COALESCE(AVG(psnap.steam_level), 0)::NUMERIC(10,2) as avg_level,
                    COALESCE(SUM(psnap.library_value), 0) as total_library_value,
                    COALESCE(SUM(psnap.inventory_value), 0) as total_inventory_value,
                    COALESCE(SUM(psnap.library_value + psnap.inventory_value), 0) as grand_total_value
                FROM parse_sessions ps
                LEFT JOIN profile_snapshots psnap ON ps.id = psnap.session_id
                LEFT JOIN profiles p ON psnap.profile_id = p.id
                GROUP BY ps.id, ps.parse_time, ps.parse_time_display, 
                         ps.total_profiles, ps.successful_profiles, ps.failed_profiles, ps.status
                ORDER BY ps.parse_time DESC 
                LIMIT %s
            """, (limit,))
            return cursor.fetchall()
    
    def get_session_profiles(self, session_id):
        """Получает все профили для конкретной сессии"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    p.*,
                    psnap.steam_level as snapshot_level,
                    psnap.games_count,
                    psnap.library_value,
                    psnap.inventory_value,
                    psnap.library_value + psnap.inventory_value as total_value,
                    psnap.parsed_at,
                    psnap.status as snapshot_status,
                    psnap.error_message
                FROM profile_snapshots psnap
                JOIN profiles p ON psnap.profile_id = p.id
                WHERE psnap.session_id = %s
                ORDER BY psnap.library_value + psnap.inventory_value DESC
            """, (session_id,))
            return cursor.fetchall()
    
    def get_profile_history(self, profile_id, limit=50):
        """Получает историю изменений профиля"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    s.parse_time,
                    s.parse_time_display,
                    psnap.*
                FROM profile_snapshots psnap
                JOIN parse_sessions s ON psnap.session_id = s.id
                WHERE psnap.profile_id = %s
                ORDER BY s.parse_time DESC
                LIMIT %s
            """, (profile_id, limit))
            return cursor.fetchall()
    
    def get_stats(self):
        """Получает общую статистику по БД"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    (SELECT COUNT(*) FROM profiles) as total_profiles,
                    (SELECT COUNT(*) FROM parse_sessions) as total_sessions,
                    (SELECT COUNT(*) FROM profile_snapshots) as total_snapshots,
                    (SELECT MAX(parse_time) FROM parse_sessions) as last_parse,
                    (SELECT SUM(games_count) FROM profile_snapshots) as total_games,
                    (SELECT SUM(library_value + inventory_value) FROM profile_snapshots) as total_value
            """)
            return cursor.fetchone()

    def get_session_by_id(self, session_id):
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    ps.id as session_id,
                    ps.parse_time,
                    ps.parse_time_display,
                    ps.total_profiles,
                    ps.successful_profiles,
                    ps.failed_profiles,
                    ps.status,
                    COUNT(DISTINCT p.country) as countries_count,
                    COALESCE(SUM(psnap.games_count), 0) as total_games,
                    COALESCE(AVG(psnap.steam_level), 0)::NUMERIC(10,2) as avg_level,
                    COALESCE(SUM(psnap.library_value), 0) as total_library_value,
                    COALESCE(SUM(psnap.inventory_value), 0) as total_inventory_value,
                    COALESCE(SUM(psnap.library_value + psnap.inventory_value), 0) as grand_total_value
                FROM parse_sessions ps
                LEFT JOIN profile_snapshots psnap ON ps.id = psnap.session_id
                LEFT JOIN profiles p ON psnap.profile_id = p.id
                WHERE ps.id = %s
                GROUP BY ps.id, ps.parse_time, ps.parse_time_display, 
                         ps.total_profiles, ps.successful_profiles, ps.failed_profiles, ps.status
            """, (session_id,))
            return cursor.fetchone()

# ==================== STEAM PARSER ====================

class SteamParser:
    def __init__(self, db_manager, silent=False):
        self.api_key = STEAM_API_KEY
        self.db = db_manager
        self.silent = silent
    
    def extract_steam_id(self, input_str: str) -> str:
        if re.match(r'^\d{17}$', input_str):
            return input_str
        match = re.search(r'steamcommunity\.com/(?:profiles|id)/([a-zA-Z0-9_]+)', input_str)
        if match:
            if not match.group(1).isdigit():
                return self._resolve_vanity_url(match.group(1))
            return match.group(1)
        match = re.search(r'steamcommunity\.com/profiles/(\d{17})', input_str)
        if match:
            return match.group(1)
        return input_str
    
    def _resolve_vanity_url(self, vanity_name: str) -> str:
        try:
            url = "https://api.steampowered.com/ISteamUser/ResolveVanityURL/v1/"
            params = {'key': self.api_key, 'vanityurl': vanity_name}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if data['response']['success'] == 1:
                return data['response']['steamid']
        except:
            pass
        return ""
    
    def get_player_info(self, steam_id: str) -> dict:
        if not self.api_key:
            return {'personaname': f'User_{steam_id[-8:]}', 'loccountrycode': 'RU',
                    'avatarfull': '', 'profileurl': f'https://steamcommunity.com/profiles/{steam_id}', 'steamid': steam_id}
        try:
            url = "https://api.steampowered.com/ISteamUser/GetPlayerSummaries/v2/"
            params = {'key': self.api_key, 'steamids': steam_id}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if data['response']['players']:
                    return data['response']['players'][0]
        except Exception as e:
            if not self.silent:
                print(f"❌ Ошибка API для {steam_id}: {str(e)}")
        return {'personaname': f'User_{steam_id[-8:]}', 'loccountrycode': 'Unknown',
                'avatarfull': '', 'profileurl': f'https://steamcommunity.com/profiles/{steam_id}', 'steamid': steam_id}
    
    def get_steam_level(self, steam_id: str) -> int:
        if not self.api_key:
            return 10
        try:
            url = "https://api.steampowered.com/IPlayerService/GetSteamLevel/v1/"
            params = {'key': self.api_key, 'steamid': steam_id}
            response = requests.get(url, params=params, timeout=10)
            data = response.json()
            if 'response' in data and 'player_level' in data['response']:
                return data['response']['player_level']
        except:
            pass
        return 10
    
    def get_owned_games(self, steam_id: str) -> dict:
        if not self.api_key:
            return {'game_count': 50, 'games': []}
        try:
            url = "https://api.steampowered.com/IPlayerService/GetOwnedGames/v1/"
            params = {'key': self.api_key, 'steamid': steam_id, 'include_appinfo': 1, 'include_played_free_games': 1}
            response = requests.get(url, params=params, timeout=15)
            data = response.json()
            if 'response' in data:
                return data['response']
        except:
            pass
        return {'game_count': 0, 'games': []}
    
    def get_games_count(self, steam_id: str) -> int:
        games_data = self.get_owned_games(steam_id)
        return games_data.get('game_count', 0)
    
    def get_library_value(self, steam_id: str) -> float:
        if not self.api_key:
            return 500.0
        try:
            games_data = self.get_owned_games(steam_id)
            if not games_data or 'games' not in games_data:
                return 0
            games = games_data['games']
            return len(games) * 10.0 if games else 0
        except:
            return 0
    
    def get_inventory_value(self, steam_id: str) -> float:
        if not self.api_key:
            return 100.0
        try:
            url = f"https://steamcommunity.com/inventory/{steam_id}/730/2"
            params = {'l': 'russian', 'count': 50}
            response = requests.get(url, params=params, timeout=10)
            if response.status_code == 200:
                data = response.json()
                if 'assets' in data:
                    return len(data['assets']) * 5.0
        except:
            pass
        return 0
    
    def parse_account(self, account_input: str) -> dict:
        result = {'input': account_input, 'success': False, 'error': None, 'data': {}}
        try:
            steam_id = self.extract_steam_id(account_input)
            if not steam_id:
                result['error'] = "Не удалось извлечь SteamID"
                return result
            player_info = self.get_player_info(steam_id)
            if not player_info:
                result['error'] = "Не удалось получить данные аккаунта"
                return result
            steam_level = self.get_steam_level(steam_id)
            games_count = self.get_games_count(steam_id)
            library_value = self.get_library_value(steam_id)
            inventory_value = self.get_inventory_value(steam_id)
            result['data'] = {
                'steam_id': steam_id,
                'nickname': player_info.get('personaname', 'Неизвестно'),
                'country': player_info.get('loccountrycode', 'Неизвестно'),
                'avatar': player_info.get('avatarfull', ''),
                'steam_level': steam_level,
                'games_count': games_count,
                'library_value': round(library_value, 2),
                'inventory_value': round(inventory_value, 2),
                'profile_url': player_info.get('profileurl', f'https://steamcommunity.com/profiles/{steam_id}'),
                'parsed_at': datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            }
            result['success'] = True
        except Exception as e:
            result['error'] = str(e)
        return result
    
    def parse_all_accounts(self):
        session_id = self.db.create_parse_session()
        if not session_id:
            return None, 0, 0
        successful = 0
        failed = 0
        for account in STEAM_ACCOUNTS:
            result = self.parse_account(account)
            if result['success']:
                profile_id = self.db.get_or_create_profile(result['data']['steam_id'], result['data'])
                if profile_id:
                    self.db.save_profile_snapshot(session_id, profile_id, result['data'])
                    successful += 1
            else:
                failed += 1
            time.sleep(1)
        self.db.update_session_stats(session_id, len(STEAM_ACCOUNTS), successful, failed)
        return session_id, successful, failed


def run_parser():
    """Точка входа для запуска парсера (cron / Airflow)"""
    print("=" * 50)
    print(f"Запуск парсинга: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("=" * 50)
    db = DatabaseManager(DB_CONFIG, silent=False)
    parser = SteamParser(db, silent=False)
    session_id, successful, failed = parser.parse_all_accounts()
    print(f"✅ Готово. Сессия: {session_id}, Успешно: {successful}, Ошибок: {failed}")
    print("=" * 50)
    return session_id, successful, failed


if __name__ == "__main__":
    run_parser()