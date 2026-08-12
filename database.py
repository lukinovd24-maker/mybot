import sqlite3

DB_NAME = "bot_data.db"

def init_db():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    
    # Таблица пользователей
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            is_blocked INTEGER DEFAULT 0
        )
    """)
    
    # Таблица админов
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS admins (
            user_id INTEGER PRIMARY KEY,
            username TEXT
        )
    """)
    
    # Таблица топиков
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS topics (
            user_id INTEGER PRIMARY KEY,
            thread_id INTEGER
        )
    """)
    
    # Таблица счётчиков статистики
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS stats (
            key TEXT PRIMARY KEY,
            value INTEGER DEFAULT 0
        )
    """)
    
    cursor.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('user_messages', 0)")
    cursor.execute("INSERT OR IGNORE INTO stats (key, value) VALUES ('admin_replies', 0)")
    
    conn.commit()
    conn.close()

def add_user(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR IGNORE INTO users (user_id, is_blocked) VALUES (?, 0)", (user_id,))
    cursor.execute("UPDATE users SET is_blocked = 0 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def set_user_blocked(user_id, blocked=True):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    val = 1 if blocked else 0
    cursor.execute("UPDATE users SET is_blocked = ? WHERE user_id = ?", (val, user_id))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM users WHERE is_blocked = 0")
    rows = cursor.fetchall()
    conn.close()
    return [row[0] for row in rows]

def get_user_counts():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT COUNT(*) FROM users")
    total = cursor.fetchone()[0]
    
    cursor.execute("SELECT COUNT(*) FROM users WHERE is_blocked = 1")
    blocked = cursor.fetchone()[0]
    
    conn.close()
    return total, blocked

def increment_stat(key):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("UPDATE stats SET value = value + 1 WHERE key = ?", (key,))
    conn.commit()
    conn.close()

def get_stats():
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT key, value FROM stats")
    rows = cursor.fetchall()
    conn.close()
    return dict(rows)

def add_admin(user_id, username=""):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO admins (user_id, username) VALUES (?, ?)", (user_id, username))
    conn.commit()
    conn.close()

def is_admin(user_id, owner_id):
    if user_id == owner_id:
        return True
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM admins WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row is not None

def save_topic(user_id, thread_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("INSERT OR REPLACE INTO topics (user_id, thread_id) VALUES (?, ?)", (user_id, thread_id))
    conn.commit()
    conn.close()

def get_thread_id(user_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT thread_id FROM topics WHERE user_id = ?", (user_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None

def get_user_by_thread(thread_id):
    conn = sqlite3.connect(DB_NAME)
    cursor = conn.cursor()
    cursor.execute("SELECT user_id FROM topics WHERE thread_id = ?", (thread_id,))
    row = cursor.fetchone()
    conn.close()
    return row[0] if row else None
