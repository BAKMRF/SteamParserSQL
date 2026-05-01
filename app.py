import streamlit as st
import pandas as pd
from datetime import datetime
import plotly.express as px
import plotly.graph_objects as go
from parser import DatabaseManager, SteamParser, DB_CONFIG, STEAM_API_KEY

# ==================== ФУНКЦИИ ДЛЯ STREAMLIT ====================

def format_currency(value):
    """Форматирует валюту"""
    return f"${float(value):,.2f}"

def main():
    st.set_page_config(
        page_title="Steam Parser with PostgreSQL",
        page_icon="🎮",
        layout="wide"
    )
    
    st.title("🎮 Steam Account Parser with PostgreSQL")
    
    # Инициализация сервисов (silent=True для веба)
    db = DatabaseManager(DB_CONFIG, silent=True)
    parser = SteamParser(db, silent=True)
    
    # Боковая панель
    with st.sidebar:
        st.header("⚙️ Управление")
        
        if st.button("🚀 Запустить парсинг сейчас", type="primary", use_container_width=True):
            with st.spinner("Парсинг аккаунтов..."):
                session_id, successful, failed = parser.parse_all_accounts()
                
                if successful:
                    st.success(f"✅ Успешно обработано: {successful} аккаунтов")
                    if failed:
                        st.warning(f"⚠️ Ошибок: {failed}")
                    st.info(f"ID сессии: {session_id}")
                else:
                    st.error("❌ Не удалось обработать ни одного аккаунта")
        
        st.divider()
        st.header("📅 История парсинга")
        
        try:
            sessions = db.get_sessions(limit=50)
            
            if sessions:
                st.success(f"📊 Всего сессий: {len(sessions)}")
                
                session_options = {}
                for s in sessions:
                    label = f"{s['parse_time_display']} | ✅ {s['successful_profiles']}/{s['total_profiles']} | 💰 ${float(s['grand_total_value']):,.0f}"
                    session_options[label] = s['session_id']
                
                selected_label = st.selectbox("Выберите сессию:", list(session_options.keys()))
                
                if st.button("📖 Показать сессию", use_container_width=True):
                    st.session_state.selected_session_id = session_options[selected_label]
                    st.session_state.pop('selected_profile_id', None)
                    st.rerun()
                
                if st.button("📊 Все сессии", use_container_width=True):
                    st.session_state.show_all_sessions = True
                    st.session_state.pop('selected_session_id', None)
                    st.session_state.pop('selected_profile_id', None)
                    st.rerun()
            else:
                st.info("📭 Сессий пока нет")
        except Exception as e:
            st.error(f"Ошибка загрузки сессий: {e}")
        
        st.divider()
        
        try:
            stats = db.get_stats()
            if stats:
                st.header("💾 Статистика БД")
                st.metric("Профилей", stats['total_profiles'])
                st.metric("Сессий", stats['total_sessions'])
                st.metric("Снимков", stats['total_snapshots'])
                if stats['total_value']:
                    st.metric("Общая стоимость", format_currency(stats['total_value']))
        except:
            pass
    
    # ==================== ОСНОВНАЯ ОБЛАСТЬ ====================
    
    # Режим: история профиля
    if 'selected_profile_id' in st.session_state:
        st.subheader(f"📈 История профиля: {st.session_state.get('selected_profile_name', '')}")
        history = db.get_profile_history(st.session_state.selected_profile_id)
        if history:
            df = pd.DataFrame(history)
            df['parse_time'] = pd.to_datetime(df['parse_time'])
            
            col1, col2 = st.columns(2)
            with col1:
                fig = px.line(df, x='parse_time', y='steam_level', title="Изменение уровня Steam")
                st.plotly_chart(fig, use_container_width=True)
            with col2:
                fig = px.line(df, x='parse_time', y='games_count', title="Изменение количества игр")
                st.plotly_chart(fig, use_container_width=True)
            
            fig = px.line(df, x='parse_time', y=['library_value', 'inventory_value', 'total_value'],
                         title="Изменение стоимости")
            st.plotly_chart(fig, use_container_width=True)
            
            st.dataframe(df[['parse_time_display', 'steam_level', 'games_count', 'library_value', 'inventory_value', 'total_value']],
                         use_container_width=True)
        else:
            st.info("Нет данных истории для этого профиля")
        
        if st.button("⬅️ Назад к сессии"):
            st.session_state.pop('selected_profile_id', None)
            st.rerun()
    
    # Режим: просмотр сессии
    elif 'selected_session_id' in st.session_state:
        session_id = st.session_state.selected_session_id
        session_data = db.get_session_by_id(session_id)
        
        if session_data:
            st.header(f"📄 Сессия от {session_data['parse_time_display']}")
            
            col1, col2, col3, col4, col5 = st.columns(5)
            with col1:
                st.metric("Всего", session_data['total_profiles'])
            with col2:
                st.metric("Успешно", session_data['successful_profiles'])
            with col3:
                st.metric("Игр", session_data['total_games'] or 0)
            with col4:
                st.metric("Ср. уровень", f"{float(session_data['avg_level']):.1f}")
            with col5:
                st.metric("Стоимость", format_currency(session_data['grand_total_value']))
            
            profiles = db.get_session_profiles(session_id)
            
            if profiles:
                st.subheader("📊 Визуализация")
                tab1, tab2, tab3 = st.tabs(["📈 Стоимость", "🎮 Игры", "🌍 Страны"])
                
                with tab1:
                    fig = go.Figure()
                    names = [p['nickname'] for p in profiles]
                    fig.add_trace(go.Bar(name='Библиотека', x=names, y=[float(p['library_value']) for p in profiles]))
                    fig.add_trace(go.Bar(name='Инвентарь', x=names, y=[float(p['inventory_value']) for p in profiles]))
                    fig.update_layout(title="Стоимость по аккаунтам", barmode='group', height=400)
                    st.plotly_chart(fig, use_container_width=True)
                
                with tab2:
                    fig = px.bar(x=[p['nickname'] for p in profiles], y=[p['games_count'] for p in profiles],
                                 title="Количество игр", height=400)
                    st.plotly_chart(fig, use_container_width=True)
                
                with tab3:
                    country_counts = {}
                    for p in profiles:
                        country = p['country'] or 'Неизвестно'
                        country_counts[country] = country_counts.get(country, 0) + 1
                    fig = px.pie(values=list(country_counts.values()), names=list(country_counts.keys()),
                                 title="Страны", height=400)
                    st.plotly_chart(fig, use_container_width=True)
                
                st.subheader("👤 Аккаунты")
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
                            st.write(f"**Игр:** {profile['games_count']}")
                            st.write(f"**Библиотека:** {format_currency(profile['library_value'])}")
                            st.write(f"**Инвентарь:** {format_currency(profile['inventory_value'])}")
                            st.write(f"**Всего:** {format_currency(profile['total_value'])}")
                            
                            if st.button(f"📈 История", key=f"hist_{profile['id']}"):
                                st.session_state.selected_profile_id = profile['id']
                                st.session_state.selected_profile_name = profile['nickname']
                                st.rerun()
                
                if st.button("⬅️ Назад к списку"):
                    st.session_state.pop('selected_session_id', None)
                    st.rerun()
    
    # Режим: все сессии
    elif 'show_all_sessions' in st.session_state:
        st.header("📊 Все сессии")
        sessions = db.get_sessions(limit=100)
        if sessions:
            df = pd.DataFrame(sessions)
            df['parse_time'] = pd.to_datetime(df['parse_time'])
            display_df = df[['parse_time_display', 'total_profiles', 'successful_profiles',
                           'failed_profiles', 'total_games', 'avg_level', 'grand_total_value']].copy()
            display_df['grand_total_value'] = display_df['grand_total_value'].apply(format_currency)
            st.dataframe(display_df, use_container_width=True)
            if st.button("⬅️ Назад"):
                st.session_state.pop('show_all_sessions', None)
                st.rerun()
    
    # Главная страница
    else:
        st.header("📊 Система мониторинга Steam аккаунтов")
        st.info("""
        ### Возможности:
        - PostgreSQL хранилище
        - История изменений
        - Графики и аналитика
        - Экспорт отчетов
        """)
        
        col1, col2 = st.columns(2)
        with col1:
            st.success("✅ Steam API: OK" if STEAM_API_KEY else "❌ Steam API: Нет ключа")
        with col2:
            try:
                stats = db.get_stats()
                st.success(f"✅ PostgreSQL: OK (профилей: {stats['total_profiles']})")
            except:
                st.error("❌ PostgreSQL: Ошибка")

if __name__ == "__main__":
    main()