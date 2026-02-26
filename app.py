import streamlit as st
import pandas as pd
import requests
import os
import re
import time
from datetime import datetime, timedelta
import base64
import plotly.express as px
import plotly.graph_objects as go
import numpy as np
from docx import Document
from docx.shared import Inches, Pt, RGBColor
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.enum.table import WD_TABLE_ALIGNMENT
import json
import schedule
import threading
from pathlib import Path
import psycopg2
from psycopg2.extras import RealDictCursor, Json
from contextlib import contextmanager
from dotenv import load_dotenv

# ==================== КОНФИГУРАЦИЯ ====================

load_dotenv()

# Настройки PostgreSQL
DB_CONFIG = {
    'host': os.getenv('DB_HOST', 'localhost'),
    'port': os.getenv('DB_PORT', '5432'),
    'database': os.getenv('DB_NAME', 'steam_parser'),
    'user': os.getenv('DB_USER', 'steam_user'),
    'password': os.getenv('DB_PASSWORD', 'steam_password')
}

STEAM_API_KEY = os.getenv("STEAM_API_KEY", "")
DEMO_MODE = False

STEAM_ACCOUNTS = [
    'https://steamcommunity.com/profiles/76561199001022272',
    'https://steamcommunity.com/profiles/76561199219594998',
    'https://steamcommunity.com/profiles/76561199384092020',
    'https://steamcommunity.com/profiles/76561198333882340',
    'https://steamcommunity.com/profiles/76561199038225456',
    'https://steamcommunity.com/profiles/76561199082417445',
]

# Папки для хранения данных
BASE_DIR = Path(__file__).parent
DATA_DIR = BASE_DIR / "data"
WORD_REPORTS_DIR = DATA_DIR / "word_reports"

DATA_DIR.mkdir(exist_ok=True)
WORD_REPORTS_DIR.mkdir(exist_ok=True)

# ==================== КЛАСС ДЛЯ РАБОТЫ С БД ====================

class DatabaseManager:
    def __init__(self, config):
        self.config = config
        self._init_db()
    
    @contextmanager
    def get_connection(self):
        """Контекстный менеджер для подключения к БД"""
        conn = None
        try:
            conn = psycopg2.connect(**self.config)
            yield conn
        except Exception as e:
            print(f"Ошибка подключения к БД: {e}")
            raise
        finally:
            if conn:
                conn.close()
    
    @contextmanager
    def get_cursor(self, cursor_factory=RealDictCursor):
        """Контекстный менеджер для курсора"""
        with self.get_connection() as conn:
            cursor = conn.cursor(cursor_factory=cursor_factory)
            try:
                yield cursor
                conn.commit()
            except Exception:
                conn.rollback()
                raise
            finally:
                cursor.close()
    
    def _init_db(self):
        """Проверка подключения к БД"""
        try:
            with self.get_cursor() as cursor:
                cursor.execute("SELECT 1")
                print("✅ Подключение к PostgreSQL установлено")
        except Exception as e:
            print(f"❌ Ошибка подключения к PostgreSQL: {e}")
            print("Убедитесь, что Docker контейнер запущен:")
            print("  docker-compose up -d")
    
    def create_parse_session(self, parse_time=None):
        """Создает новую сессию парсинга"""
        if not parse_time:
            parse_time = datetime.now()
        
        parse_time_display = parse_time.strftime("%d.%m.%Y %H:%M:%S")
        timestamp_str = parse_time.strftime("%Y%m%d_%H%M%S")
        
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO parse_sessions 
                (parse_time, parse_time_display, timestamp_str, status)
                VALUES (%s, %s, %s, 'pending')
                RETURNING id
            """, (parse_time, parse_time_display, timestamp_str))
            
            result = cursor.fetchone()
            return result['id'] if result else None
    
    def update_session_stats(self, session_id, total_profiles, successful, failed):
        """Обновляет статистику сессии"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                UPDATE parse_sessions 
                SET total_profiles = %s,
                    successful_profiles = %s,
                    failed_profiles = %s,
                    status = CASE 
                        WHEN %s > 0 THEN 'success'
                        ELSE 'failed'
                    END
                WHERE id = %s
            """, (total_profiles, successful, failed, successful, session_id))
    
    def get_or_create_profile(self, steam_id, profile_data):
        """Получает или создает профиль"""
        with self.get_cursor() as cursor:
            # Пытаемся найти существующий профиль
            cursor.execute("""
                SELECT id FROM profiles WHERE steam_id = %s
            """, (steam_id,))
            
            result = cursor.fetchone()
            
            if result:
                profile_id = result['id']
                # Обновляем данные профиля
                cursor.execute("""
                    UPDATE profiles 
                    SET nickname = %s,
                        country = %s,
                        avatar_url = %s,
                        steam_level = %s,
                        profile_url = %s,
                        last_updated = CURRENT_TIMESTAMP
                    WHERE id = %s
                """, (
                    profile_data.get('nickname'),
                    profile_data.get('country'),
                    profile_data.get('avatar'),
                    profile_data.get('steam_level'),
                    profile_data.get('profile_url'),
                    profile_id
                ))
                return profile_id
            else:
                # Создаем новый профиль
                cursor.execute("""
                    INSERT INTO profiles 
                    (steam_id, nickname, country, avatar_url, steam_level, profile_url)
                    VALUES (%s, %s, %s, %s, %s, %s)
                    RETURNING id
                """, (
                    steam_id,
                    profile_data.get('nickname'),
                    profile_data.get('country'),
                    profile_data.get('avatar'),
                    profile_data.get('steam_level'),
                    profile_data.get('profile_url')
                ))
                result = cursor.fetchone()
                return result['id'] if result else None
    
    def save_profile_snapshot(self, session_id, profile_id, profile_data, status='success', error=None):
        """Сохраняет снимок данных профиля"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                INSERT INTO profile_snapshots 
                (session_id, profile_id, steam_level, games_count, 
                 library_value, inventory_value, parsed_at, status, error_message)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (session_id, profile_id) 
                DO UPDATE SET
                    steam_level = EXCLUDED.steam_level,
                    games_count = EXCLUDED.games_count,
                    library_value = EXCLUDED.library_value,
                    inventory_value = EXCLUDED.inventory_value,
                    parsed_at = EXCLUDED.parsed_at,
                    status = EXCLUDED.status,
                    error_message = EXCLUDED.error_message
            """, (
                session_id, profile_id,
                profile_data.get('steam_level', 0),
                profile_data.get('games_count', 0),
                profile_data.get('library_value', 0),
                profile_data.get('inventory_value', 0),
                profile_data.get('parsed_at', datetime.now()),
                status, error
            ))
    
    def get_sessions(self, limit=100):
        """Получает список сессий парсинга"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM session_summary 
                ORDER BY parse_time DESC 
                LIMIT %s
            """, (limit,))
            return cursor.fetchall()
    
    def get_session_by_id(self, session_id):
        """Получает данные сессии по ID"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT * FROM session_summary WHERE session_id = %s
            """, (session_id,))
            return cursor.fetchone()
    
    def get_session_profiles(self, session_id):
        """Получает все профили для конкретной сессии"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    p.*,
                    ps.steam_level as snapshot_level,
                    ps.games_count,
                    ps.library_value,
                    ps.inventory_value,
                    ps.total_value,
                    ps.parsed_at,
                    ps.status as snapshot_status,
                    ps.error_message
                FROM profile_snapshots ps
                JOIN profiles p ON ps.profile_id = p.id
                WHERE ps.session_id = %s
                ORDER BY ps.total_value DESC
            """, (session_id,))
            return cursor.fetchall()
    
    def get_profile_history(self, profile_id, limit=50):
        """Получает историю изменений профиля"""
        with self.get_cursor() as cursor:
            cursor.execute("""
                SELECT 
                    s.parse_time,
                    s.parse_time_display,
                    ps.*
                FROM profile_snapshots ps
                JOIN parse_sessions s ON ps.session_id = s.id
                WHERE ps.profile_id = %s
                ORDER BY s.parse_time DESC
                LIMIT %s
            """, (profile_id, limit))
            return cursor.fetchall()
    
    def delete_session(self, session_id):
        """Удаляет сессию и связанные данные"""
        with self.get_cursor() as cursor:
            cursor.execute("DELETE FROM parse_sessions WHERE id = %s", (session_id,))

# ==================== КЛАСС ПАРСЕРА (обновленный) ====================

class SteamParser:
    def __init__(self, db_manager):
        self.api_key = STEAM_API_KEY
        self.demo_mode = DEMO_MODE
        self.db = db_manager
        
        print(f"🔧 Инициализация парсера:")
        print(f"   Режим: {'ДЕМО' if self.demo_mode else 'РЕАЛЬНЫЙ'}")
        print(f"   API ключ: {'ЕСТЬ' if self.api_key else 'НЕТ'}")
    
    # ... (все методы extract_steam_id, _resolve_vanity_url, 
    # get_player_info, get_steam_level, get_owned_games, 
    # get_games_count, get_library_value, get_inventory_value 
    # остаются без изменений) ...
    
    def parse_all_accounts(self):
        """Парсит все аккаунты и сохраняет в БД"""
        print("\n🚀 Начало парсинга всех аккаунтов")
        
        # Создаем сессию парсинга
        session_id = self.db.create_parse_session()
        
        if not session_id:
            print("❌ Не удалось создать сессию парсинга")
            return None, None, []
        
        successful_profiles = []
        failed_profiles = []
        
        for i, account in enumerate(STEAM_ACCOUNTS):
            print(f"\n📊 Аккаунт {i+1}/{len(STEAM_ACCOUNTS)}")
            result = self.parse_account(account)
            
            if result['success']:
                # Получаем или создаем профиль
                profile_id = self.db.get_or_create_profile(
                    result['data']['steam_id'], 
                    result['data']
                )
                
                if profile_id:
                    # Сохраняем снимок данных
                    self.db.save_profile_snapshot(
                        session_id, 
                        profile_id, 
                        result['data']
                    )
                    successful_profiles.append(result['data'])
                    print(f"   ✅ {result['data']['nickname']}")
                else:
                    failed_profiles.append({
                        'account': account,
                        'error': 'Не удалось сохранить профиль в БД'
                    })
                    print(f"   ❌ Ошибка сохранения в БД")
            else:
                failed_profiles.append({
                    'account': account,
                    'error': result.get('error', 'Неизвестная ошибка')
                })
                print(f"   ❌ {result.get('error', 'Ошибка')}")
            
            time.sleep(1)  # Задержка между запросами
        
        # Обновляем статистику сессии
        self.db.update_session_stats(
            session_id,
            len(STEAM_ACCOUNTS),
            len(successful_profiles),
            len(failed_profiles)
        )
        
        return session_id, successful_profiles, failed_profiles

# ==================== ОБНОВЛЕННАЯ ФУНКЦИЯ MAIN ====================

def main():
    st.set_page_config(
        page_title="Steam Parser with PostgreSQL",
        page_icon="🎮",
        layout="wide"
    )
    
    st.title("🎮 Steam Account Parser with PostgreSQL")
    
    # Инициализация сервисов
    db = DatabaseManager(DB_CONFIG)
    parser = SteamParser(db)
    
    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Управление")
        
        # Ручной парсинг
        if st.button("🚀 Запустить парсинг сейчас", type="primary", use_container_width=True):
            with st.spinner("Парсинг аккаунтов..."):
                session_id, successful, failed = parser.parse_all_accounts()
                
                if successful:
                    st.success(f"✅ Успешно обработано: {len(successful)} аккаунтов")
                    if failed:
                        st.warning(f"⚠️ Ошибок: {len(failed)}")
                    
                    # Показываем детали
                    with st.expander("📋 Детали парсинга"):
                        for profile in successful:
                            st.write(f"✅ {profile['nickname']} (Уровень: {profile['steam_level']})")
                        for fail in failed:
                            st.write(f"❌ {fail['account']}: {fail['error']}")
                    
                    st.info(f"ID сессии: {session_id}")
                else:
                    st.error("❌ Не удалось обработать ни одного аккаунта")
        
        st.divider()
        
        # История сессий
        st.header("📅 История парсинга")
        
        sessions = db.get_sessions(limit=50)
        
        if sessions:
            st.success(f"📊 Всего сессий: {len(sessions)}")
            
            # Создаем словарь для выбора
            session_options = {}
            for s in sessions:
                label = f"{s['parse_time_display']} | ✅ {s['successful_profiles']}/{s['total_profiles']} | 💰 ${s['grand_total_value']:,.0f}"
                session_options[label] = s['session_id']
            
            selected_label = st.selectbox(
                "Выберите сессию для просмотра:",
                list(session_options.keys())
            )
            
            if st.button("📖 Показать выбранную сессию", use_container_width=True):
                st.session_state.selected_session_id = session_options[selected_label]
                st.rerun()
            
            # Кнопка для просмотра всех сессий в таблице
            if st.button("📊 Показать все сессии", use_container_width=True):
                st.session_state.show_all_sessions = True
                st.rerun()
        else:
            st.info("📭 Сессий пока нет")
        
        st.divider()
        
        # Информация о БД
        st.header("💾 База данных")
        st.code(f"""
Хост: {DB_CONFIG['host']}
Порт: {DB_CONFIG['port']}
БД: {DB_CONFIG['database']}
Пользователь: {DB_CONFIG['user']}
        """)
        
        st.info("""
        **PgAdmin доступен:**
        http://localhost:5050
        Email: admin@steam.com
        Пароль: admin
        """)
    
    # Основная область
    if 'selected_session_id' in st.session_state:
        # Показываем выбранную сессию
        session_id = st.session_state.selected_session_id
        session_data = db.get_session_by_id(session_id)
        
        if session_data:
            st.header(f"📄 Сессия от {session_data['parse_time_display']}")
            
            # Сводная статистика
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Всего аккаунтов", session_data['total_profiles'])
            with col2:
                st.metric("Успешно", session_data['successful_profiles'])
            with col3:
                st.metric("Всего игр", session_data['total_games'] or 0)
            with col4:
                st.metric("Средний уровень", f"{session_data['avg_level']:.1f}")
            with col5:
                st.metric("Общая стоимость", f"${session_data['grand_total_value']:,.2f}")
            
            # Получаем профили сессии
            profiles = db.get_session_profiles(session_id)
            
            if profiles:
                # Графики
                st.subheader("📊 Визуализация данных")
                
                tab1, tab2, tab3 = st.tabs(["📈 Стоимость", "🎮 Игры", "🌍 Страны"])
                
                with tab1:
                    # График стоимости
                    fig = go.Figure()
                    
                    names = [p['nickname'] for p in profiles]
                    library_values = [float(p['library_value']) for p in profiles]
                    inventory_values = [float(p['inventory_value']) for p in profiles]
                    
                    fig.add_trace(go.Bar(
                        name='Библиотека',
                        x=names,
                        y=library_values,
                        marker_color='rgb(55, 83, 109)'
                    ))
                    
                    fig.add_trace(go.Bar(
                        name='Инвентарь',
                        x=names,
                        y=inventory_values,
                        marker_color='rgb(26, 118, 255)'
                    ))
                    
                    fig.update_layout(
                        title="Стоимость библиотеки и инвентаря по аккаунтам",
                        xaxis_title="Аккаунт",
                        yaxis_title="Стоимость ($)",
                        barmode='group'
                    )
                    
                    st.plotly_chart(fig, use_container_width=True)
                
                with tab2:
                    # График количества игр
                    fig = px.bar(
                        x=[p['nickname'] for p in profiles],
                        y=[p['games_count'] for p in profiles],
                        title="Количество игр в библиотеке",
                        labels={'x': 'Аккаунт', 'y': 'Количество игр'}
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                with tab3:
                    # Статистика по странам
                    country_counts = {}
                    for p in profiles:
                        country = p['country'] or 'Неизвестно'
                        country_counts[country] = country_counts.get(country, 0) + 1
                    
                    fig = px.pie(
                        values=list(country_counts.values()),
                        names=list(country_counts.keys()),
                        title="Распределение по странам"
                    )
                    st.plotly_chart(fig, use_container_width=True)
                
                # Детальная информация
                st.subheader("👤 Детальная информация по аккаунтам")
                
                for profile in profiles:
                    with st.expander(f"🎮 {profile['nickname']}"):
                        col1, col2 = st.columns([1, 3])
                        
                        with col1:
                            if profile['avatar_url']:
                                st.image(profile['avatar_url'], width=100)
                            st.metric("Уровень", profile['snapshot_level'])
                        
                        with col2:
                            st.write(f"**Страна:** {profile['country'] or 'Неизвестно'}")
                            st.write(f"**SteamID:** `{profile['steam_id']}`")
                            st.write(f"**Игр в библиотеке:** {profile['games_count']}")
                            st.write(f"**Стоимость библиотеки:** ${float(profile['library_value']):,.2f}")
                            st.write(f"**Стоимость инвентаря:** ${float(profile['inventory_value']):,.2f}")
                            st.write(f"**Общая стоимость:** ${float(profile['total_value']):,.2f}")
                            st.write(f"**Ссылка:** {profile['profile_url']}")
                            
                            # Кнопка для просмотра истории профиля
                            if st.button(f"📈 История профиля", key=f"history_{profile['id']}"):
                                st.session_state.selected_profile_id = profile['id']
                                st.session_state.selected_profile_name = profile['nickname']
                                st.rerun()
                
                # Кнопка возврата
                if st.button("⬅️ Назад к списку сессий"):
                    del st.session_state.selected_session_id
                    if 'selected_profile_id' in st.session_state:
                        del st.session_state.selected_profile_id
                    st.rerun()
        
        # Показываем историю профиля если выбрана
        if 'selected_profile_id' in st.session_state:
            st.divider()
            st.subheader(f"📈 История профиля: {st.session_state.selected_profile_name}")
            
            history = db.get_profile_history(st.session_state.selected_profile_id)
            
            if history:
                # Создаем DataFrame для графика
                df = pd.DataFrame(history)
                df['parse_time'] = pd.to_datetime(df['parse_time'])
                
                # График изменения уровня
                fig = px.line(
                    df, 
                    x='parse_time', 
                    y='steam_level',
                    title="Изменение уровня Steam",
                    labels={'parse_time': 'Дата', 'steam_level': 'Уровень'}
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # График изменения стоимости
                fig = px.line(
                    df, 
                    x='parse_time', 
                    y=['library_value', 'inventory_value', 'total_value'],
                    title="Изменение стоимости",
                    labels={'parse_time': 'Дата', 'value': 'Стоимость ($)'}
                )
                st.plotly_chart(fig, use_container_width=True)
                
                # Таблица истории
                st.dataframe(
                    df[['parse_time_display', 'steam_level', 'games_count', 
                        'library_value', 'inventory_value', 'total_value']],
                    use_container_width=True
                )
            else:
                st.info("Нет данных истории для этого профиля")
    
    elif 'show_all_sessions' in st.session_state:
        # Показываем все сессии в виде таблицы
        st.header("📊 Все сессии парсинга")
        
        sessions = db.get_sessions(limit=100)
        
        if sessions:
            df = pd.DataFrame(sessions)
            df['parse_time'] = pd.to_datetime(df['parse_time'])
            
            # Форматируем для отображения
            display_df = df[['parse_time_display', 'total_profiles', 'successful_profiles',
                           'failed_profiles', 'total_games', 'avg_level', 'grand_total_value']].copy()
            
            display_df.columns = ['Время парсинга', 'Всего', 'Успешно', 'Ошибок',
                                'Всего игр', 'Ср. уровень', 'Общая стоимость']
            
            display_df['Общая стоимость'] = display_df['Общая стоимость'].apply(
                lambda x: f"${float(x):,.2f}" if x else "$0"
            )
            
            st.dataframe(display_df, use_container_width=True)
            
            # График по сессиям
            fig = px.line(
                df, 
                x='parse_time', 
                y='grand_total_value',
                title="Динамика общей стоимости",
                labels={'parse_time': 'Дата', 'grand_total_value': 'Общая стоимость ($)'}
            )
            st.plotly_chart(fig, use_container_width=True)
            
            if st.button("⬅️ Назад"):
                del st.session_state.show_all_sessions
                st.rerun()
        else:
            st.info("Нет данных")
    
    else:
        # Главная страница
        st.header("📊 Система мониторинга Steam аккаунтов с PostgreSQL")
        
        col1, col2 = st.columns(2)
        
        with col1:
            st.info("""
            ### 🎯 Новые возможности:
            1. **PostgreSQL хранилище** всех данных
            2. **История изменений** каждого профиля
            3. **Сравнение сессий** во времени
            4. **Графики и аналитика** в реальном времени
            5. **PgAdmin** для управления БД
            """)
        
        with col2:
            # Последние сессии
            st.subheader("🕒 Последние сессии")
            sessions = db.get_sessions(limit=5)
            
            if sessions:
                for s in sessions:
                    st.write(f"📅 {s['parse_time_display']}")
                    st.write(f"   ✅ {s['successful_profiles']}/{s['total_profiles']} | 💰 ${s['grand_total_value']:,.2f}")
                    st.divider()
            else:
                st.write("Нет данных. Запустите парсинг!")
        
        # Статус подключения
        st.divider()
        st.subheader("🔧 Статус системы")
        
        col1, col2, col3 = st.columns(3)
        
        with col1:
            if STEAM_API_KEY:
                st.success("✅ Steam API: OK")
            else:
                st.error("❌ Steam API: Нет ключа")
        
        with col2:
            try:
                with db.get_cursor() as cursor:
                    cursor.execute("SELECT COUNT(*) FROM profiles")
                    count = cursor.fetchone()['count']
                    st.success(f"✅ PostgreSQL: OK (профилей: {count})")
            except:
                st.error("❌ PostgreSQL: Ошибка подключения")
        
        with col3:
            st.info(f"📊 Аккаунтов в мониторинге: {len(STEAM_ACCOUNTS)}")

# ==================== ФУНКЦИЯ ДЛЯ АВТОМАТИЧЕСКОГО ПАРСИНГА ====================

def run_auto_parse():
    """Функция для запуска из cron"""
    print("=" * 50)
    print("Запуск авто-парсинга Steam аккаунтов")
    print(f"Время запуска: {datetime.now().strftime('%d.%m.%Y %H:%M:%S')}")
    print("=" * 50)
    
    db = DatabaseManager(DB_CONFIG)
    parser = SteamParser(db)
    
    session_id, successful, failed = parser.parse_all_accounts()
    
    if successful:
        print(f"✅ Отчет сохранен в БД (session_id: {session_id})")
        print(f"   Обработано: {len(successful)}/{len(STEAM_ACCOUNTS)}")
    else:
        print("❌ Не удалось обработать ни одного аккаунта")
    
    print("=" * 50)

# ==================== ЗАПУСК ====================

if __name__ == "__main__":
    import sys
    if len(sys.argv) > 1 and sys.argv[1] == "--auto":
        run_auto_parse()
    else:
        main()