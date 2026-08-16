# bot.py — IndyCard Бот с банковской системой

import os
import logging
import sqlite3
import json
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, FSInputFile
)
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from data.drivers import DRIVERS
from data.winners import WINNERS

load_dotenv()

# ============================================================
# НАСТРОЙКИ
# ============================================================

BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8000))
ADMIN_IDS = [7025868617, 7946032603]
DB_PATH = "indycard.db"

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# РЕДКОСТИ КАРТ (НА АНГЛИЙСКОМ)
# ============================================================

RARITIES = {
    "COMMON": {
        "emoji": "🟢",
        "rating": 10,
        "chance": 50,
        "name": "Common",
        "color": "#4CAF50",
        "icon": "📄"
    },
    "RARE": {
        "emoji": "🔵",
        "rating": 25,
        "chance": 25,
        "name": "Rare",
        "color": "#2196F3",
        "icon": "⭐"
    },
    "EPIC": {
        "emoji": "🟣",
        "rating": 40,
        "chance": 15,
        "name": "Epic",
        "color": "#9C27B0",
        "icon": "🔮"
    },
    "LEGENDARY": {
        "emoji": "🟡",
        "rating": 60,
        "chance": 7,
        "name": "Legendary",
        "color": "#FFD700",
        "icon": "👑"
    },
    "INDY_EDITION": {
        "emoji": "🔴",
        "rating": 100,
        "chance": 2,
        "name": "Indy Edition",
        "color": "#E53935",
        "icon": "🏆"
    },
    "ULTIMATE": {
        "emoji": "💎",
        "rating": 150,
        "chance": 1,
        "name": "Ultimate",
        "color": "#FF6B35",
        "icon": "🌟"
    },
}

# ============================================================
# CALLBACK DATA
# ============================================================

class CarouselCallback(CallbackData, prefix="carousel"):
    action: str
    code: str = ""
    index: int = 0

class CardActionCallback(CallbackData, prefix="card"):
    action: str
    code: str = ""

class BankCallback(CallbackData, prefix="bank"):
    action: str  # deposit, credit, repay, history
    amount: int = 0
    term: int = 0  # days

# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================

class BankStates(StatesGroup):
    waiting_deposit_amount = State()
    waiting_deposit_term = State()
    waiting_credit_amount = State()
    waiting_credit_term = State()
    waiting_repay_amount = State()

# ============================================================
# СЕССИИ
# ============================================================

user_carousel = {}

# ============================================================
# БАЗА ДАННЫХ
# ============================================================

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            balance INTEGER DEFAULT 500,
            rating INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            game_attempts INTEGER DEFAULT 3,
            last_attempt_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_cards INTEGER DEFAULT 0,
            
            -- Банковские поля
            credit_rating INTEGER DEFAULT 100,  -- 0-100
            total_deposits INTEGER DEFAULT 0,
            total_credits INTEGER DEFAULT 0,
            missed_payments INTEGER DEFAULT 0,
            is_banned_from_bank INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS user_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            quantity INTEGER DEFAULT 1,
            UNIQUE(user_id, code)
        );
        
        CREATE TABLE IF NOT EXISTS cards (
            code TEXT PRIMARY KEY,
            name TEXT,
            team TEXT,
            number INTEGER,
            rarity TEXT,
            price INTEGER,
            rating_points INTEGER DEFAULT 10,
            year INTEGER,
            image TEXT,
            change_24h REAL DEFAULT 0.0,
            base_price INTEGER DEFAULT 100
        );
        
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            code TEXT,
            amount INTEGER,
            balance_after INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            term INTEGER,  -- days
            rate INTEGER,  -- percent
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_date TIMESTAMP,
            status TEXT DEFAULT 'active',  -- active, closed, defaulted
            interest_earned INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            term INTEGER,
            rate INTEGER,
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_date TIMESTAMP,
            status TEXT DEFAULT 'active',  -- active, repaid, defaulted
            paid_amount INTEGER DEFAULT 0,
            missed_payments INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS bank_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            amount INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward_type TEXT,
            reward_value TEXT,
            max_uses INTEGER,
            used INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS promo_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            user_id INTEGER,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, user_id)
        );
        
        CREATE TABLE IF NOT EXISTS market_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_code TEXT,
            price INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        );
        
        CREATE TABLE IF NOT EXISTS pvp_battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1_id INTEGER,
            player2_id INTEGER,
            bet_type TEXT,
            bet_value TEXT,
            status TEXT DEFAULT 'waiting',
            winner_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS price_history (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            card_code TEXT,
            price INTEGER,
            change_percent REAL,
            change_reason TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS market_state (
            id INTEGER PRIMARY KEY,
            last_update DATE,
            market_data TEXT
        );
        
        CREATE TABLE IF NOT EXISTS race_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE,
            event_name TEXT,
            race_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS daily_bonus (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            date DATE,
            streak INTEGER,
            bonus INTEGER,
            UNIQUE(user_id, date)
        );
    """)
    
    seed_data()
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

def seed_data():
    conn = get_db()
    c = conn.cursor()
    
    for code, data in DRIVERS.items():
        c.execute("""
            INSERT OR IGNORE INTO cards 
            (code, name, team, number, rarity, price, rating_points, year, image, base_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code, data["name"], data["team"], data.get("number", 0),
            data["rarity"], data["price"],
            RARITIES.get(data["rarity"], {}).get("rating", 10),
            2026, data.get("image", ""), data["price"]
        ))
    
    for winner in WINNERS:
        code = f"WIN_{winner['driver'][:3].upper()}_{winner['year']}"
        c.execute("""
            INSERT OR IGNORE INTO cards 
            (code, name, team, number, rarity, price, rating_points, year, image, base_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code, winner["driver"], "Indy 500 Winner", 0,
            winner.get("rarity", "INDY_EDITION"), winner.get("price", 500),
            RARITIES.get(winner.get("rarity", "INDY_EDITION"), {}).get("rating", 100),
            winner["year"], "", winner.get("price", 500)
        ))
    
    conn.commit()
    conn.close()
    logger.info("✅ Данные загружены")

# ============================================================
# DB HELPER ФУНКЦИИ
# ============================================================

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
        "INSERT OR IGNORE INTO users (user_id, username, display_name, credit_rating) VALUES (?, ?, ?, 100)",
        (user_id, username, name)
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

def remove_card_from_user(user_id: int, code: str) -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE user_cards SET quantity = quantity - 1 WHERE user_id = ? AND code = ?", (user_id, code))
    c.execute("DELETE FROM user_cards WHERE user_id = ? AND code = ? AND quantity <= 0", (user_id, code))
    c.execute("UPDATE users SET total_cards = total_cards - 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def get_game_attempts(user_id: int) -> int:
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT game_attempts FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 3

def reset_attempts(user_id: int) -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = 3, last_attempt_reset = CURRENT_TIMESTAMP WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def add_attempt(user_id: int, amount: int = 1) -> None:
    conn = get_db()
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = game_attempts + ? WHERE user_id = ?", (amount, user_id))
    conn.commit()
    conn.close()

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

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_rarity_emoji(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("emoji", "🟢")

def get_rarity_name(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("name", "Common")

def get_rarity_icon(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("icon", "📄")

def get_attempts_display(user_id: int) -> str:
    attempts = get_game_attempts(user_id)
    full = "🎲" * attempts
    empty = "⬜" * (3 - attempts)
    return f"{full}{empty}"

# ============================================================
# БАНКОВСКИЕ ФУНКЦИИ
# ============================================================

# Кредитный рейтинг
CREDIT_LEVELS = {
    80: {"name": "Отличный", "emoji": "🌟🌟🌟", "max_credit": 50000, "rate_bonus": 0},
    60: {"name": "Хороший", "emoji": "🌟🌟", "max_credit": 20000, "rate_bonus": 5},
    40: {"name": "Средний", "emoji": "🌟", "max_credit": 5000, "rate_bonus": 10},
    20: {"name": "Низкий", "emoji": "⚠️", "max_credit": 500, "rate_bonus": 20},
    0: {"name": "Плохой", "emoji": "🚫", "max_credit": 0, "rate_bonus": 0},
}

def get_credit_level(rating: int) -> dict:
    for threshold in sorted(CREDIT_LEVELS.keys(), reverse=True):
        if rating >= threshold:
            return CREDIT_LEVELS[threshold]
    return CREDIT_LEVELS[0]

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
    new_rating = max(0, min(100, new_rating))  # Ограничиваем 0-100
    c.execute("UPDATE users SET credit_rating = ? WHERE user_id = ?", (new_rating, user_id))
    conn.commit()
    conn.close()
    return new_rating

def get_active_deposits(user_id: int) -> list:
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, amount, term, rate, start_date, end_date, status, interest_earned 
        FROM deposits WHERE user_id = ? AND status = 'active'
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_active_credits(user_id: int) -> list:
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT id, amount, term, rate, start_date, end_date, status, paid_amount, missed_payments 
        FROM credits WHERE user_id = ? AND status = 'active'
    """, (user_id,))
    rows = c.fetchall()
    conn.close()
    return rows

def get_credit_limit(user_id: int) -> int:
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    return level["max_credit"]

def get_deposit_rates() -> dict:
    return {
        7: {"rate": 5, "min": 100, "max": 10000},
        30: {"rate": 12, "min": 500, "max": 50000},
        90: {"rate": 25, "min": 1000, "max": 100000},
    }

def get_credit_rates() -> dict:
    return {
        3: {"rate": 10, "min": 10, "max": 500},
        7: {"rate": 15, "min": 100, "max": 5000},
        30: {"rate": 20, "min": 500, "max": 50000},
    }

def create_deposit(user_id: int, amount: int, term: int) -> dict:
    rates = get_deposit_rates()
    if term not in rates:
        return {"error": "Неверный срок депозита"}
    
    rate_data = rates[term]
    if amount < rate_data["min"] or amount > rate_data["max"]:
        return {"error": f"Сумма должна быть от {rate_data['min']} до {rate_data['max']} 💰"}
    
    user = get_user(user_id)
    if user["balance"] < amount:
        return {"error": "Недостаточно средств"}
    
    # Списываем деньги
    update_balance(user_id, -amount, "deposit")
    
    # Создаём депозит
    conn = get_db()
    c = conn.cursor()
    end_date = datetime.now() + timedelta(days=term)
    c.execute("""
        INSERT INTO deposits (user_id, amount, term, rate, end_date)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, term, rate_data["rate"], end_date))
    
    c.execute("UPDATE users SET total_deposits = total_deposits + 1 WHERE user_id = ?", (user_id,))
    c.execute("""
        INSERT INTO bank_logs (user_id, action, amount, details)
        VALUES (?, 'deposit', ?, ?)
    """, (user_id, amount, f"Депозит на {term} дней под {rate_data['rate']}%"))
    
    conn.commit()
    deposit_id = c.lastrowid
    conn.close()
    
    return {
        "success": True,
        "deposit_id": deposit_id,
        "amount": amount,
        "term": term,
        "rate": rate_data["rate"],
        "end_date": end_date,
        "profit": int(amount * rate_data["rate"] / 100)
    }

def create_credit(user_id: int, amount: int, term: int) -> dict:
    rates = get_credit_rates()
    if term not in rates:
        return {"error": "Неверный срок кредита"}
    
    rate_data = rates[term]
    if amount < rate_data["min"] or amount > rate_data["max"]:
        return {"error": f"Сумма должна быть от {rate_data['min']} до {rate_data['max']} 💰"}
    
    # Проверяем кредитный рейтинг
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    if level["max_credit"] == 0:
        return {"error": "❌ Ваш кредитный рейтинг слишком низкий. Банк отказывает в кредите."}
    
    if amount > level["max_credit"]:
        return {"error": f"❌ Ваш кредитный рейтинг ({level['emoji']}) позволяет взять максимум {level['max_credit']} 💰"}
    
    # Проверяем активные кредиты
    active_credits = get_active_credits(user_id)
    total_credit = sum(c[1] for c in active_credits)  # сумма активных кредитов
    if total_credit + amount > level["max_credit"]:
        return {"error": f"❌ У вас уже есть кредиты на {total_credit} 💰. Максимум {level['max_credit']} 💰"}
    
    # Создаём кредит
    conn = get_db()
    c = conn.cursor()
    end_date = datetime.now() + timedelta(days=term)
    final_rate = rate_data["rate"] + level["rate_bonus"]  # +% за плохой рейтинг
    
    c.execute("""
        INSERT INTO credits (user_id, amount, term, rate, end_date)
        VALUES (?, ?, ?, ?, ?)
    """, (user_id, amount, term, final_rate, end_date))
    
    # Зачисляем деньги
    update_balance(user_id, amount, "credit")
    
    c.execute("UPDATE users SET total_credits = total_credits + 1 WHERE user_id = ?", (user_id,))
    c.execute("""
        INSERT INTO bank_logs (user_id, action, amount, details)
        VALUES (?, 'credit', ?, ?)
    """, (user_id, amount, f"Кредит на {term} дней под {final_rate}%"))
    
    conn.commit()
    credit_id = c.lastrowid
    conn.close()
    
    return {
        "success": True,
        "credit_id": credit_id,
        "amount": amount,
        "term": term,
        "rate": final_rate,
        "end_date": end_date,
        "to_pay": int(amount * (1 + final_rate / 100))
    }

def repay_credit(user_id: int, credit_id: int, amount: int = None) -> dict:
    conn = get_db()
    c = conn.cursor()
    
    c.execute("""
        SELECT amount, rate, paid_amount, status, term, end_date 
        FROM credits WHERE id = ? AND user_id = ?
    """, (credit_id, user_id))
    credit = c.fetchone()
    
    if not credit:
        conn.close()
        return {"error": "Кредит не найден"}
    
    if credit[3] != "active":
        conn.close()
        return {"error": "Кредит уже погашен"}
    
    total_amount = credit[0]  # total
    rate = credit[1]
    paid = credit[2]
    
    total_owed = int(total_amount * (1 + rate / 100))
    remaining = total_owed - paid
    
    if amount is None or amount >= remaining:
        amount_to_pay = remaining
    else:
        amount_to_pay = amount
    
    user = get_user(user_id)
    if user["balance"] < amount_to_pay:
        conn.close()
        return {"error": f"Недостаточно средств. Нужно {amount_to_pay} 💰"}
    
    # Платим
    update_balance(user_id, -amount_to_pay, "credit_repay")
    new_paid = paid + amount_to_pay
    c.execute("UPDATE credits SET paid_amount = ? WHERE id = ?", (new_paid, credit_id))
    
    # Если погасили полностью
    if new_paid >= total_owed:
        c.execute("UPDATE credits SET status = 'repaid' WHERE id = ?", (credit_id,))
        # Повышаем кредитный рейтинг
        update_credit_rating(user_id, 5)
        conn.commit()
        conn.close()
        return {
            "success": True,
            "message": "✅ Кредит полностью погашен! Кредитный рейтинг повышен!",
            "paid": amount_to_pay
        }
    
    conn.commit()
    conn.close()
    return {
        "success": True,
        "message": f"✅ Оплачено {amount_to_pay} 💰. Остаток: {total_owed - new_paid} 💰",
        "paid": amount_to_pay
    }

def get_bank_stats(user_id: int) -> dict:
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    deposits = get_active_deposits(user_id)
    credits = get_active_credits(user_id)
    
    total_deposits = sum(d[1] for d in deposits)
    total_credits = sum(c[1] for c in credits)
    
    return {
        "rating": rating,
        "level": level,
        "deposits_count": len(deposits),
        "total_deposits": total_deposits,
        "credits_count": len(credits),
        "total_credits": total_credits,
        "credit_limit": level["max_credit"],
    }

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu(user_id: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🎴 Коллекция", callback_data="collection")
    builder.button(text="🏦 Рынок", callback_data="market")
    builder.button(text="👤 Профиль", callback_data="profile")
    builder.button(text="🏪 Магазин", callback_data="shop")
    builder.button(text="⚔️ PvP Арена", callback_data="pvp_menu")
    builder.button(text="🏦 Банк", callback_data="bank_menu")
    builder.button(text="ℹ️ О проекте", callback_data="about")
    
    if user_id and is_admin(user_id):
        builder.button(text="👑 INDY Admin", callback_data="admin_panel")
    
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()

def back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def bank_menu(user_id: int) -> InlineKeyboardMarkup:
    stats = get_bank_stats(user_id)
    level = stats["level"]
    
    builder = InlineKeyboardBuilder()
    builder.button(
        text=f"💰 Депозиты ({stats['deposits_count']})",
        callback_data="bank_deposits"
    )
    builder.button(
        text=f"💳 Кредиты ({stats['credits_count']})",
        callback_data="bank_credits"
    )
    builder.button(
        text=f"📊 Мой рейтинг: {level['emoji']}",
        callback_data="bank_rating"
    )
    builder.button(
        text="📋 История операций",
        callback_data="bank_history"
    )
    builder.button(
        text="🔙 Назад",
        callback_data="back_to_menu"
    )
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def deposit_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 7 дней (5%)", callback_data=BankCallback(action="deposit", term=7).pack())
    builder.button(text="📅 30 дней (12%)", callback_data=BankCallback(action="deposit", term=30).pack())
    builder.button(text="📅 90 дней (25%)", callback_data=BankCallback(action="deposit", term=90).pack())
    builder.button(text="🔙 Назад", callback_data="bank_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def credit_menu(user_id: int) -> InlineKeyboardMarkup:
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    builder = InlineKeyboardBuilder()
    
    if level["max_credit"] > 0:
        builder.button(
            text="📅 3 дня (10%)",
            callback_data=BankCallback(action="credit", term=3).pack()
        )
        builder.button(
            text="📅 7 дней (15%)",
            callback_data=BankCallback(action="credit", term=7).pack()
        )
        builder.button(
            text="📅 30 дней (20%)",
            callback_data=BankCallback(action="credit", term=30).pack()
        )
    else:
        builder.button(
            text="❌ Кредиты недоступны",
            callback_data="bank_rating_guide"
        )
    
    builder.button(text="🔙 Назад", callback_data="bank_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def credit_rating_guide() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я понял", callback_data="bank_menu")
    builder.adjust(1)
    return builder.as_markup()

# ============================================================
# БОТ
# ============================================================

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()
router = Router()

# ============================================================
# ОБРАБОТЧИКИ — ОБЩИЕ
# ============================================================

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    create_user(message.from_user.id, message.from_user.username)
    
    user = get_user(message.from_user.id)
    attempts = get_game_attempts(message.from_user.id)
    attempts_display = get_attempts_display(message.from_user.id)
    
    await message.answer(
        f"🏁 **IndyCard Exchange**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {attempts_display}\n\n"
        f"Выбирай действие:",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery) -> None:
    user = get_user(callback.from_user.id)
    attempts = get_game_attempts(callback.from_user.id)
    attempts_display = get_attempts_display(callback.from_user.id)
    
    await callback.message.edit_text(
        f"🏁 **Главное меню**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {attempts_display}",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "ℹ️ **IndyCard Exchange**\n\n"
        "Карточная игра по мотивам IndyCar.\n\n"
        "🎴 Собирай карты пилотов и легенд\n"
        "🏦 Торгуй на бирже и рынке\n"
        "⚔️ Играй в PvP на кубиках\n"
        "🎲 Используй попытки для получения карт\n"
        "🏦 Инвестируй в банке или бери кредиты\n\n"
        "Разработчики: @Scanialove, @Gabriella1488",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# БАНК — ГЛАВНОЕ МЕНЮ
# ============================================================

@router.callback_query(F.data == "bank_menu")
async def cb_bank_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    user = get_user(user_id)
    stats = get_bank_stats(user_id)
    
    await callback.message.edit_text(
        f"🏦 **Банк IndyCard**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"📊 Кредитный рейтинг: {stats['level']['emoji']} {stats['level']['name']}\n"
        f"   ({stats['rating']}/100)\n\n"
        f"📈 Активные депозиты: {stats['deposits_count']}\n"
        f"   💰 Сумма: {stats['total_deposits']} 💰\n"
        f"📉 Активные кредиты: {stats['credits_count']}\n"
        f"   💰 Сумма: {stats['total_credits']} 💰\n"
        f"🏦 Кредитный лимит: {stats['credit_limit']} 💰\n\n"
        f"Выберите действие:",
        reply_markup=bank_menu(user_id),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# БАНК — ДЕПОЗИТЫ
# ============================================================

@router.callback_query(F.data == "bank_deposits")
async def cb_bank_deposits(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    deposits = get_active_deposits(user_id)
    
    if deposits:
        text = "💰 **Ваши депозиты**\n\n"
        for dep in deposits:
            dep_id, amount, term, rate, start, end, status, interest = dep
            days_left = (datetime.fromisoformat(end) - datetime.now()).days
            text += (
                f"📅 Депозит #{dep_id}\n"
                f"   💰 {amount} 💰 | {term} дней | {rate}%\n"
                f"   📆 Осталось: {days_left} дней\n"
                f"   📈 Прибыль: {interest} 💰\n\n"
            )
    else:
        text = "💰 **Депозиты**\n\nУ вас нет активных депозитов.\n\n"
        text += "📊 **Доступные депозиты:**\n"
        text += "• 7 дней — 5% (мин 100 💰)\n"
        text += "• 30 дней — 12% (мин 500 💰)\n"
        text += "• 90 дней — 25% (мин 1000 💰)\n\n"
        text += "Выберите срок для открытия депозита:"
    
    await callback.message.edit_text(
        text,
        reply_markup=deposit_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(BankCallback.filter(F.action == "deposit"))
async def cb_deposit_create(callback: CallbackQuery, callback_data: BankCallback, state: FSMContext) -> None:
    term = callback_data.term
    rates = get_deposit_rates()
    rate_data = rates[term]
    
    await state.update_data(term=term, rate=rate_data["rate"])
    await state.set_state(BankStates.waiting_deposit_amount)
    
    await callback.message.edit_text(
        f"💰 **Открытие депозита**\n\n"
        f"📅 Срок: {term} дней\n"
        f"📈 Ставка: {rate_data['rate']}%\n"
        f"💳 Мин. сумма: {rate_data['min']} 💰\n"
        f"💳 Макс. сумма: {rate_data['max']} 💰\n\n"
        f"Введите сумму депозита:",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(BankStates.waiting_deposit_amount)
async def process_deposit_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Введите положительное число")
            return
        
        data = await state.get_data()
        term = data["term"]
        
        result = create_deposit(message.from_user.id, amount, term)
        
        if "error" in result:
            await message.answer(f"❌ {result['error']}")
            return
        
        user = get_user(message.from_user.id)
        await message.answer(
            f"✅ **Депозит открыт!**\n\n"
            f"💰 Сумма: {result['amount']} 💰\n"
            f"📅 Срок: {result['term']} дней\n"
            f"📈 Ставка: {result['rate']}%\n"
            f"📆 Дата окончания: {result['end_date'][:10]}\n"
            f"💵 Прибыль: {result['profit']} 💰\n\n"
            f"💰 Новый баланс: {user['balance']} 💰",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Введите число")
    
    await state.clear()

# ============================================================
# БАНК — КРЕДИТЫ
# ============================================================

@router.callback_query(F.data == "bank_credits")
async def cb_bank_credits(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    credits = get_active_credits(user_id)
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    if credits:
        text = "💳 **Ваши кредиты**\n\n"
        for cr in credits:
            cr_id, amount, term, rate, start, end, status, paid, missed = cr
            total_owed = int(amount * (1 + rate / 100))
            remaining = total_owed - paid
            days_left = (datetime.fromisoformat(end) - datetime.now()).days
            
            text += (
                f"📅 Кредит #{cr_id}\n"
                f"   💰 {amount} 💰 | {term} дней | {rate}%\n"
                f"   📆 Осталось: {days_left} дней\n"
                f"   💵 Остаток: {remaining} 💰\n"
                f"   ⚠️ Просрочек: {missed}\n\n"
            )
    else:
        text = "💳 **Кредиты**\n\nУ вас нет активных кредитов.\n\n"
        text += f"📊 Ваш кредитный рейтинг: {level['emoji']} {level['name']}\n"
        text += f"🏦 Кредитный лимит: {level['max_credit']} 💰\n\n"
        
        if level["max_credit"] > 0:
            text += "📊 **Доступные кредиты:**\n"
            text += "• 3 дня — 10% (до 500 💰)\n"
            text += "• 7 дней — 15% (до 5000 💰)\n"
            text += "• 30 дней — 20% (до 50000 💰)\n\n"
            text += "Выберите срок для оформления кредита:"
        else:
            text += "❌ **Кредиты недоступны!**\n"
            text += "Ваш кредитный рейтинг слишком низкий.\n"
            text += "Чтобы повысить рейтинг:\n"
            text += "• Открывайте депозиты и не снимайте досрочно\n"
            text += "• Вовремя погашайте кредиты\n"
            text += "• Не допускайте просрочек"
    
    await callback.message.edit_text(
        text,
        reply_markup=credit_menu(user_id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(BankCallback.filter(F.action == "credit"))
async def cb_credit_create(callback: CallbackQuery, callback_data: BankCallback, state: FSMContext) -> None:
    user_id = callback.from_user.id
    term = callback_data.term
    
    rates = get_credit_rates()
    rate_data = rates[term]
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    if level["max_credit"] == 0:
        await callback.message.edit_text(
            "❌ **Кредиты недоступны!**\n\n"
            "Ваш кредитный рейтинг слишком низкий.\n\n"
            "📊 **Как повысить кредитный рейтинг:**\n"
            "• Открывайте депозиты и не снимайте досрочно\n"
            "• Вовремя погашайте кредиты\n"
            "• Не допускайте просрочек\n\n"
            "💰 Чем выше рейтинг, тем больше кредитный лимит.",
            reply_markup=credit_rating_guide(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    final_rate = rate_data["rate"] + level["rate_bonus"]
    
    await state.update_data(term=term, rate=final_rate)
    await state.set_state(BankStates.waiting_credit_amount)
    
    await callback.message.edit_text(
        f"💳 **Оформление кредита**\n\n"
        f"📅 Срок: {term} дней\n"
        f"📈 Ставка: {final_rate}%\n"
        f"💳 Мин. сумма: {rate_data['min']} 💰\n"
        f"💳 Макс. сумма: {rate_data['max']} 💰\n"
        f"🏦 Ваш лимит: {level['max_credit']} 💰\n"
        f"📊 Рейтинг: {level['emoji']} {level['name']}\n\n"
        f"Введите сумму кредита:",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(BankStates.waiting_credit_amount)
async def process_credit_amount(message: Message, state: FSMContext) -> None:
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Введите положительное число")
            return
        
        data = await state.get_data()
        term = data["term"]
        
        result = create_credit(message.from_user.id, amount, term)
        
        if "error" in result:
            await message.answer(f"❌ {result['error']}")
            return
        
        user = get_user(message.from_user.id)
        await message.answer(
            f"✅ **Кредит одобрен!**\n\n"
            f"💰 Сумма: {result['amount']} 💰\n"
            f"📅 Срок: {result['term']} дней\n"
            f"📈 Ставка: {result['rate']}%\n"
            f"📆 Дата возврата: {result['end_date'][:10]}\n"
            f"💳 К возврату: {result['to_pay']} 💰\n\n"
            f"💰 Новый баланс: {user['balance']} 💰\n\n"
            f"⚠️ **Важно:** при просрочке более 7 дней банк\n"
            f"начинает изымать ваши карты в счёт долга!",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Введите число")
    
    await state.clear()

# ============================================================
# БАНК — КРЕДИТНЫЙ РЕЙТИНГ
# ============================================================

@router.callback_query(F.data == "bank_rating")
async def cb_bank_rating(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    text = f"📊 **Кредитный рейтинг**\n\n"
    text += f"Текущий рейтинг: {level['emoji']} {level['name']}\n"
    text += f"Значение: {rating}/100\n"
    text += f"Кредитный лимит: {level['max_credit']} 💰\n"
    text += f"Бонус к ставке: +{level['rate_bonus']}%\n\n"
    
    text += "📋 **Уровни рейтинга:**\n"
    for threshold in sorted(CREDIT_LEVELS.keys(), reverse=True):
        lvl = CREDIT_LEVELS[threshold]
        if rating >= threshold:
            text += f"✅ {lvl['emoji']} {lvl['name']} ({threshold}+) — ваш уровень\n"
        else:
            text += f"⬜ {lvl['emoji']} {lvl['name']} ({threshold}+)\n"
    
    text += "\n📌 **Как повысить рейтинг:**\n"
    text += "✅ Открывайте депозиты и не снимайте досрочно\n"
    text += "✅ Вовремя погашайте кредиты\n"
    text += "✅ Не допускайте просрочек\n"
    text += "✅ Чем больше операций, тем выше рейтинг"
    
    await callback.message.edit_text(
        text,
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "bank_rating_guide")
async def cb_bank_rating_guide(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    
    text = "📊 **Как повысить кредитный рейтинг**\n\n"
    text += "1️⃣ **Открывайте депозиты**\n"
    text += "   • Деньги работают, вы получаете проценты\n"
    text += "   • Чем больше депозит, тем выше рейтинг\n\n"
    text += "2️⃣ **Вовремя погашайте кредиты**\n"
    text += "   • Платите строго в срок\n"
    text += "   • Досрочное погашение повышает рейтинг\n\n"
    text += "3️⃣ **Избегайте просрочек**\n"
    text += "   • Просрочка 1-3 дня: предупреждение\n"
    text += "   • Просрочка 4-7 дней: штраф 50%\n"
    text += "   • Просрочка 8-14 дней: изъятие карт\n"
    text += "   • Просрочка >14 дней: арест счёта\n\n"
    text += "4️⃣ **Совершайте операции в банке**\n"
    text += "   • Чем больше операций, тем выше рейтинг\n"
    text += "   • Доверие банка растёт со временем"
    
    await callback.message.edit_text(
        text,
        reply_markup=credit_rating_guide(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# БАНК — ИСТОРИЯ
# ============================================================

@router.callback_query(F.data == "bank_history")
async def cb_bank_history(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    
    conn = get_db()
    c = conn.cursor()
    c.execute("""
        SELECT action, amount, details, timestamp 
        FROM bank_logs 
        WHERE user_id = ? 
        ORDER BY timestamp DESC 
        LIMIT 10
    """, (user_id,))
    logs = c.fetchall()
    conn.close()
    
    if not logs:
        text = "📋 **История операций**\n\nПока нет операций в банке."
    else:
        text = "📋 **История операций**\n\n"
        for action, amount, details, ts in logs:
            emoji = "💳" if action == "credit" else "💰" if action == "deposit" else "📊"
            sign = "+" if action == "credit" else "-" if action == "deposit" else ""
            text += f"{emoji} {ts[:10]} {details}\n"
            text += f"   {sign}{amount} 💰\n\n"
    
    await callback.message.edit_text(
        text,
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# КОЛЛЕКЦИЯ (ОСНОВНАЯ)
# ============================================================

@router.callback_query(F.data == "collection")
async def cb_collection(callback: CallbackQuery) -> None:
    user = get_user(callback.from_user.id)
    attempts = get_game_attempts(callback.from_user.id)
    attempts_display = get_attempts_display(callback.from_user.id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои карты", callback_data="my_cards")
    builder.button(text="🎲 Получить карту", callback_data="get_card")
    builder.button(text="🔄 Обмен карт", callback_data="trade_menu")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1, 1)
    
    await callback.message.edit_text(
        f"🎴 **Коллекция**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {attempts_display}\n\n"
        f"Здесь ты можешь посмотреть свои карты\n"
        f"и получить новые!",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# КАРУСЕЛЬ КАРТ
# ============================================================

@router.callback_query(F.data == "my_cards")
async def cb_my_cards(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cards = get_user_cards(user_id)
    
    if not cards:
        await callback.message.edit_text(
            "📭 **У тебя пока нет карт**\n\n"
            "Используй попытки, чтобы получить свои первые карты!\n"
            "🎲 Получить карту — в меню Коллекции",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    card_codes = list(cards.keys())
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, 
                    "EPIC": 3, "RARE": 4, "COMMON": 5}
    card_codes.sort(key=lambda x: rarity_order.get(get_card_info(x)["rarity"], 99))
    
    user_carousel[user_id] = {"cards": card_codes, "index": 0}
    await show_card(callback.message, user_id, 0, callback)

async def show_card(message: Message, user_id: int, index: int, callback: Optional[CallbackQuery] = None) -> None:
    data = user_carousel.get(user_id)
    if not data:
        return
    
    cards = data["cards"]
    if index >= len(cards):
        index = 0
        data["index"] = 0
    
    code = cards[index]
    card = get_card_info(code)
    user = get_user(user_id)
    
    if not card:
        return
    
    rarity = card["rarity"]
    emoji = get_rarity_emoji(rarity)
    rarity_name = get_rarity_name(rarity)
    icon = get_rarity_icon(rarity)
    
    total = len(cards)
    
    text = (
        f"🏎️ **{card['name']}**\n\n"
        f"📋 Код: `{card['code']}`\n"
        f"🏁 Команда: {card['team']}\n"
        f"🔢 Номер: #{card['number']}\n"
        f"🎴 Редкость: {emoji} {rarity_name}\n"
        f"⭐ Рейтинг: {card['rating_points']}\n"
        f"💰 Цена: {card['price']} 💰\n"
        f"📈 Изменение: {card.get('change_24h', 0):+.1f}%\n"
        f"📅 Сезон: {card.get('year', 2026)}\n\n"
        f"📦 Количество: {cards.count(code)}\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(user_id)}\n"
        f"📊 {index+1}/{total}"
    )
    
    builder = InlineKeyboardBuilder()
    
    if total > 1:
        prev_idx = (index - 1) % total
        next_idx = (index + 1) % total
        builder.button(
            text="◀️",
            callback_data=CarouselCallback(action="prev", code=cards[prev_idx], index=prev_idx).pack()
        )
        builder.button(
            text=f"{index+1}/{total}",
            callback_data=CarouselCallback(action="view", code=code, index=index).pack()
        )
        builder.button(
            text="▶️",
            callback_data=CarouselCallback(action="next", code=cards[next_idx], index=next_idx).pack()
        )
        builder.adjust(3)
    
    builder.button(text="🔙 Назад", callback_data="collection")
    builder.adjust(3, 1)
    
    try:
        if card.get("image") and card["image"].startswith("http"):
            await message.edit_photo(
                photo=card["image"],
                caption=text,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
        else:
            await message.edit_text(
                f"{icon} **{card['name']}**\n\n" + text,
                reply_markup=builder.as_markup(),
                parse_mode="Markdown"
            )
    except Exception as e:
        await message.edit_text(
            f"{icon} **{card['name']}**\n\n" + text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    if callback:
        await callback.answer()

@router.callback_query(CarouselCallback.filter())
async def cb_carousel(callback: CallbackQuery, callback_data: CarouselCallback) -> None:
    user_id = callback.from_user.id
    action = callback_data.action
    
    data = user_carousel.get(user_id)
    if not data:
        await callback.answer("❌ Сессия истекла")
        return
    
    cards = data["cards"]
    if not cards:
        await callback.answer("❌ Нет карт")
        return
    
    if action == "prev" or action == "next":
        index = callback_data.index
        data["index"] = index
        user_carousel[user_id] = data
        await show_card(callback.message, user_id, index, callback)
    elif action == "view":
        await show_card(callback.message, user_id, callback_data.index, callback)

# ============================================================
# ПОЛУЧИТЬ КАРТУ
# ============================================================

@router.callback_query(F.data == "get_card")
async def cb_get_card(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    
    if not use_attempt(user_id):
        await callback.answer("❌ Нет попыток! Купи в магазине или подожди", show_alert=True)
        return
    
    rarities = [r for r, d in RARITIES.items() for _ in range(d["chance"])]
    rarity = random.choice(rarities)
    
    conn = get_db()
    c = conn.cursor()
    c.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await callback.answer("❌ Нет карт", show_alert=True)
        return
    
    code = row[0]
    add_card_to_user(user_id, code)
    card = get_card_info(code)
    user = get_user(user_id)
    
    emoji = get_rarity_emoji(card["rarity"])
    rarity_name = get_rarity_name(card["rarity"])
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои карты", callback_data="my_cards")
    builder.button(text="🎲 Ещё раз", callback_data="get_card")
    builder.button(text="🔙 Назад", callback_data="collection")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        f"🎲 **Получена карта!**\n\n"
        f"{emoji} **{card['name']}**\n"
        f"🏁 {card['team']}\n"
        f"🎴 {rarity_name}\n"
        f"💰 {card['price']} 💰\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(user_id)}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ПРОФИЛЬ
# ============================================================

@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery) -> None:
    user = get_user(callback.from_user.id)
    cards = get_user_cards(callback.from_user.id)
    attempts = get_game_attempts(callback.from_user.id)
    attempts_display = get_attempts_display(callback.from_user.id)
    total_cards = sum(cards.values()) if cards else 0
    rating = get_credit_rating(callback.from_user.id)
    level = get_credit_level(rating)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Промокод", callback_data="promo_enter")
    builder.button(text="📋 Моя статистика", callback_data="my_stats")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        f"👤 **Профиль**\n\n"
        f"🆔 ID: {callback.from_user.id}\n"
        f"👤 Имя: {user['username'] or user['display_name']}\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {attempts_display}\n"
        f"🎴 Всего карт: {total_cards}\n"
        f"📦 Уникальных: {len(cards)} / 33\n"
        f"🏆 Рейтинг: {user['rating']}\n"
        f"🏦 Кредитный рейтинг: {level['emoji']} {level['name']} ({rating})\n\n"
        f"📅 В игре с: {user['created_at'][:10] if user.get('created_at') else 'сегодня'}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# МАГАЗИН
# ============================================================

@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery) -> None:
    user = get_user(callback.from_user.id)
    attempts = get_game_attempts(callback.from_user.id)
    attempts_display = get_attempts_display(callback.from_user.id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Попытка +1 (50 💰)", callback_data="buy_attempt_1")
    builder.button(text="🎲 Попытка +3 (120 💰)", callback_data="buy_attempt_3")
    builder.button(text="💎 Улучшить карту", callback_data="upgrade_card")
    builder.button(text="🔄 Слияние карт", callback_data="merge_cards")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1, 1, 1)
    
    await callback.message.edit_text(
        f"🏪 **Магазин**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {attempts_display}\n\n"
        f"Выбери, что хочешь купить:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "buy_attempt_1")
async def cb_buy_attempt_1(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if user["balance"] < 50:
        await callback.answer("❌ Нужно 50 💰", show_alert=True)
        return
    
    update_balance(user_id, -50, "shop_attempt")
    add_attempt(user_id, 1)
    
    user = get_user(user_id)
    await callback.message.edit_text(
        f"✅ **Попытка куплена!**\n\n"
        f"🎲 Попытки: {get_attempts_display(user_id)}\n"
        f"💰 Баланс: {user['balance']} 💰",
        reply_markup=shop_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "buy_attempt_3")
async def cb_buy_attempt_3(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    if user["balance"] < 120:
        await callback.answer("❌ Нужно 120 💰", show_alert=True)
        return
    
    update_balance(user_id, -120, "shop_attempt")
    add_attempt(user_id, 3)
    
    user = get_user(user_id)
    await callback.message.edit_text(
        f"✅ **3 попытки куплены!**\n\n"
        f"🎲 Попытки: {get_attempts_display(user_id)}\n"
        f"💰 Баланс: {user['balance']} 💰",
        reply_markup=shop_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОСТАЛЬНЫЕ ЗАГЛУШКИ
# ============================================================

@router.callback_query(F.data == "market")
async def cb_market(callback: CallbackQuery) -> None:
    user = get_user(callback.from_user.id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Биржа", callback_data="exchange")
    builder.button(text="💰 Продать карту", callback_data="sell_menu")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        f"🏦 **Рынок**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n\n"
        f"⚠️ **В разработке**",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "pvp_menu")
async def cb_pvp_menu(callback: CallbackQuery) -> None:
    user = get_user(callback.from_user.id)
    attempts = get_game_attempts(callback.from_user.id)
    attempts_display = get_attempts_display(callback.from_user.id)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Создать битву", callback_data="pvp_create")
    builder.button(text="📋 Список битв", callback_data="pvp_list")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)
    
    await callback.message.edit_text(
        f"⚔️ **PvP Арена**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {attempts_display}\n\n"
        f"⚠️ **В разработке**",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ЗАПУСК
# ============================================================

async def on_startup() -> None:
    await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    logger.info(f"✅ Вебхук установлен: {WEBHOOK_URL}{WEBHOOK_PATH}")

async def on_shutdown() -> None:
    await bot.delete_webhook()
    logger.info("❌ Вебхук удалён")

def main() -> None:
    if WEBHOOK_URL:
        logger.info(f"🚀 Запуск в режиме вебхука на порту {PORT}")
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:
        logger.info("🚀 Запуск в режиме поллинга")
        dp.run_polling(bot)

if __name__ == "__main__":
    init_db()
    dp.include_router(router)
    main()
