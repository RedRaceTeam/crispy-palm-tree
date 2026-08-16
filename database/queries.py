import sqlite3
import json
from datetime import datetime, timedelta
from typing import Optional, Dict, List
from config import DB_PATH

def get_db():
    return sqlite3.connect(DB_PATH)

def get_user(user_id: int) -> Optional[dict]:
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def create_user(user_id: int, username: str) -> None:
    conn = get_db()
    c = conn.cursor()
    name = username or f"User{user_id}"
    c.execute(
        "INSERT OR IGNORE INTO users (user_id, username, display_name, credit_rating) VALUES (?, ?, ?, ?)",
        (user_id, username, name, 100)
    )
    conn.commit()
    conn.close()

def update_balance(user_id: int, amount: int, tx_type: str = "unknown", code: str = None) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = c.fetchone()[0]
    c.execute(
        "INSERT INTO transactions (user_id, type, code, amount, balance_after) VALUES (?, ?, ?, ?, ?)",
        (user_id, tx_type, code, amount, new_balance)
    )
    conn.commit()
    conn.close()
    return new_balance

def get_user_cards(user_id: int) -> Dict[str, int]:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code, quantity FROM user_cards WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}

def get_card_info(code: str) -> Optional[dict]:
    conn = get_db()
    conn.row_factory = sqlite3.Row
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    return dict(row) if row else None

def add_card_to_user(user_id: int, code: str) -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute(
        """INSERT INTO user_cards (user_id, code, quantity) VALUES (?, ?, 1) 
           ON CONFLICT(user_id, code) DO UPDATE SET quantity = quantity + 1""",
        (user_id, code)
    )
    c.execute("UPDATE users SET total_cards = total_cards + 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_game_attempts(user_id: int) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT game_attempts FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 3

def use_attempt(user_id: int) -> bool:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT game_attempts FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    if not row or row[0] <= 0:
        conn.close()
        return False
    c.execute("UPDATE users SET game_attempts = game_attempts - 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()
    return True

def add_attempt(user_id: int, amount: int = 1) -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = game_attempts + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

def reset_attempts(user_id: int) -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = 3, last_attempt_reset = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_credit_rating(user_id: int) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT credit_rating FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 100

def update_credit_rating(user_id: int, change: int) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET credit_rating = credit_rating + ? WHERE user_id = ?", (change, user_id))
    c.execute("SELECT credit_rating FROM users WHERE user_id = ?", (user_id,))
    new_rating = c.fetchone()[0]
    new_rating = max(0, min(100, new_rating))
    c.execute("UPDATE users SET credit_rating = ? WHERE user_id = ?", (new_rating, user_id))
    conn.commit()
    conn.close()
    return new_rating

def get_credit_level(rating: int) -> dict:
    levels = {
        80: {"name": "Отличный", "emoji": "🌟🌟🌟", "max_credit": 50000, "rate_bonus": 0},
        60: {"name": "Хороший", "emoji": "🌟🌟", "max_credit": 20000, "rate_bonus": 5},
        40: {"name": "Средний", "emoji": "🌟", "max_credit": 5000, "rate_bonus": 10},
        20: {"name": "Низкий", "emoji": "⚠️", "max_credit": 500, "rate_bonus": 20},
        0: {"name": "Плохой", "emoji": "🚫", "max_credit": 0, "rate_bonus": 0},
    }
    for threshold in sorted(levels.keys(), reverse=True):
        if rating >= threshold:
            return levels[threshold]
    return levels[0]
