import sqlite3

conn = sqlite3.connect("faceit_data.db")
cursor = conn.cursor()

cursor.execute("DROP TABLE IF EXISTS player_match_stats")
cursor.execute("DROP TABLE IF EXISTS matches")
cursor.execute("DROP TABLE IF EXISTS players")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS players (
        player_id TEXT PRIMARY KEY,
        nickname TEXT,
        faceit_elo INTEGER,
        skill_level INTEGER,
        last_updated TEXT
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS matches (
        match_id TEXT PRIMARY KEY,
        map TEXT,
        winning_team TEXT,
        team1_id TEXT,
        team2_id TEXT,
        date INTEGER
    )
""")

cursor.execute("""
    CREATE TABLE IF NOT EXISTS player_match_stats (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        match_id TEXT,
        player_id TEXT,
        team TEXT,
        kd_ratio REAL,
        adr REAL,
        headshot_pct REAL,
        entry_rate REAL,
        entry_success_rate REAL,
        clutch_1v1_rate REAL,
        clutch_1v2_rate REAL,
        enemies_flashed_per_round REAL,
        utility_success_rate REAL,
        utility_count_per_round REAL,
        sniper_kills_per_round REAL,
        result INTEGER,
        FOREIGN KEY (match_id) REFERENCES matches (match_id),
        FOREIGN KEY (player_id) REFERENCES players (player_id)
    )
""")

conn.commit()
print("Tables created successfully")
conn.close()