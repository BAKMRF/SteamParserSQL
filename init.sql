-- Создание базы данных (если не существует)
CREATE DATABASE steam_parser;

-- Подключаемся к базе данных
\c steam_parser;

-- Создание enum типов
CREATE TYPE parse_status AS ENUM ('success', 'failed', 'pending');

-- Таблица для сессий парсинга
CREATE TABLE parse_sessions (
    id SERIAL PRIMARY KEY,
    parse_time TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    parse_date DATE GENERATED ALWAYS AS (parse_time::DATE) STORED,
    parse_time_display VARCHAR(50),
    timestamp_str VARCHAR(20),
    total_profiles INTEGER DEFAULT 0,
    successful_profiles INTEGER DEFAULT 0,
    failed_profiles INTEGER DEFAULT 0,
    status parse_status DEFAULT 'pending',
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для профилей
CREATE TABLE profiles (
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

-- Таблица для данных парсинга (история по каждому профилю в каждой сессии)
CREATE TABLE profile_snapshots (
    id SERIAL PRIMARY KEY,
    session_id INTEGER REFERENCES parse_sessions(id) ON DELETE CASCADE,
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    steam_level INTEGER DEFAULT 0,
    games_count INTEGER DEFAULT 0,
    library_value DECIMAL(10, 2) DEFAULT 0,
    inventory_value DECIMAL(10, 2) DEFAULT 0,
    total_value DECIMAL(10, 2) GENERATED ALWAYS AS (library_value + inventory_value) STORED,
    parsed_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    status parse_status DEFAULT 'success',
    error_message TEXT,
    UNIQUE(session_id, profile_id)
);

-- Таблица для игр (справочник)
CREATE TABLE games (
    id SERIAL PRIMARY KEY,
    app_id INTEGER UNIQUE NOT NULL,
    name VARCHAR(500) NOT NULL,
    created_at TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP
);

-- Таблица для связи профилей с играми
CREATE TABLE profile_games (
    profile_id INTEGER REFERENCES profiles(id) ON DELETE CASCADE,
    game_id INTEGER REFERENCES games(id) ON DELETE CASCADE,
    playtime_forever INTEGER DEFAULT 0,
    playtime_2weeks INTEGER DEFAULT 0,
    first_seen TIMESTAMP WITH TIME ZONE DEFAULT CURRENT_TIMESTAMP,
    last_played TIMESTAMP WITH TIME ZONE,
    PRIMARY KEY (profile_id, game_id)
);

-- Создание индексов для оптимизации
CREATE INDEX idx_parse_sessions_parse_date ON parse_sessions(parse_date);
CREATE INDEX idx_parse_sessions_parse_time ON parse_sessions(parse_time);
CREATE INDEX idx_profile_snapshots_session_id ON profile_snapshots(session_id);
CREATE INDEX idx_profile_snapshots_profile_id ON profile_snapshots(profile_id);
CREATE INDEX idx_profiles_steam_id ON profiles(steam_id);
CREATE INDEX idx_profiles_last_updated ON profiles(last_updated);
CREATE INDEX idx_profile_games_profile_id ON profile_games(profile_id);

-- Функция для обновления updated_at
CREATE OR REPLACE FUNCTION update_updated_at_column()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = CURRENT_TIMESTAMP;
    RETURN NEW;
END;
$$ language 'plpgsql';

-- Триггеры для автоматического обновления updated_at
CREATE TRIGGER update_parse_sessions_updated_at 
    BEFORE UPDATE ON parse_sessions 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

CREATE TRIGGER update_profiles_updated_at 
    BEFORE UPDATE ON profiles 
    FOR EACH ROW 
    EXECUTE FUNCTION update_updated_at_column();

-- Представление для удобной агрегации данных по сессиям
CREATE VIEW session_summary AS
SELECT 
    ps.id as session_id,
    ps.parse_time,
    ps.parse_date,
    ps.parse_time_display,
    ps.total_profiles,
    ps.successful_profiles,
    ps.failed_profiles,
    ps.status,
    COUNT(DISTINCT p.country) as countries_count,
    SUM(psnap.games_count) as total_games,
    AVG(psnap.steam_level)::NUMERIC(10,2) as avg_level,
    SUM(psnap.library_value) as total_library_value,
    SUM(psnap.inventory_value) as total_inventory_value,
    SUM(psnap.total_value) as grand_total_value
FROM parse_sessions ps
LEFT JOIN profile_snapshots psnap ON ps.id = psnap.session_id
LEFT JOIN profiles p ON psnap.profile_id = p.id
GROUP BY ps.id, ps.parse_time, ps.parse_date, ps.parse_time_display, 
         ps.total_profiles, ps.successful_profiles, ps.failed_profiles, ps.status;

-- Комментарии к таблицам
COMMENT ON TABLE parse_sessions IS 'Сессии парсинга';
COMMENT ON TABLE profiles IS 'Профили Steam';
COMMENT ON TABLE profile_snapshots IS 'Снимки данных профилей по сессиям';
COMMENT ON TABLE games IS 'Справочник игр';
COMMENT ON TABLE profile_games IS 'Игры профилей';