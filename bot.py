# bot.py — IndyCard Бот (aiogram 3.x, асинхронный, один файл)

import os
import logging
import json
import random
import string
from datetime import datetime, timedelta
from typing import Dict, Optional, Any

import aiosqlite
from aiohttp import web
from dotenv import load_dotenv

from aiogram import Bot, Dispatcher, Router, F
from aiogram.filters import Command, StateFilter
from aiogram.filters.callback_data import CallbackData
from aiogram.types import (
    Message, CallbackQuery, InlineKeyboardMarkup, 
    InlineKeyboardButton, User
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================
# РЕДКОСТИ КАРТ
# ============================================================

RARITIES = {
    "REGULAR": {"emoji": "🟢", "rating": 10, "chance": 50, "name": "Обычная"},
    "RARE": {"emoji": "⭐", "rating": 25, "chance": 25, "name": "Редкая"},
    "EXCLUSIVE": {"emoji": "🔮", "rating": 40, "chance": 15, "name": "Эксклюзив"},
    "LEGENDARY": {"emoji": "💎", "rating": 60, "chance": 7, "name": "Легендарная"},
    "INDY_EDITION": {"emoji": "🏁", "rating": 100, "chance": 2, "name": "Indy Edition"},
    "ULTIMATE": {"emoji": "👑", "rating": 150, "chance": 1, "name": "Ультимативная"},
}

# ============================================================
# CALLBACK DATA FACTORY (aiogram 3.x фича)
# ============================================================
# Типобезопасные callback'ы — вместо строковых F.data [citation:2][citation:4]

class CardCallback(CallbackData, prefix="card"):
    """Callback для работы с картами"""
    action: str          # view, sell, buy, etc.
    code: str = ""
    page: int = 0

class MarketCallback(CallbackData, prefix="market"):
    """Callback для рынка"""
    action: str          # buy, sell, list
    listing_id: int = 0
    card_code: str = ""

class PvpCallback(CallbackData, prefix="pvp"):
    """Callback для PvP"""
    action: str          # create, join, bet, money
    battle_id: int = 0
    amount: int = 0
    card_code: str = ""

class AdminCallback(CallbackData, prefix="admin"):
    """Callback для админки"""
    action: str          # prices, promo, stats, etc.
    card_code: str = ""
    price_change: int = 0

# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================

class PromoStates(StatesGroup):
    """Состояния для создания промокодов"""
    waiting_for_promo_type = State()
    waiting_for_card = State()
    waiting_for_coins = State()

class BetStates(StatesGroup):
    """Состояния для PvP ставок"""
    waiting_for_bet_amount = State()

# ============================================================
# БАЗА ДАННЫХ (АСИНХРОННАЯ)
# ============================================================

DB_PATH = "indycard.db"

async def init_db() -> None:
    """Асинхронная инициализация базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.executescript("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                display_name TEXT,
                balance INTEGER DEFAULT 500,
                rating INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                game_attempts INTEGER DEFAULT 3,
                last_game_attempt TIMESTAMP
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
                change_24h REAL DEFAULT 0.0
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
        await db.commit()
    
    # Загрузка данных
    await seed_data()
    logger.info("✅ База данных инициализирована")

async def seed_data() -> None:
    """Асинхронная загрузка начальных данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        for code, data in DRIVERS.items():
            await db.execute("""
                INSERT OR IGNORE INTO cards 
                (code, name, team, number, rarity, price, rating_points, year, image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, data["name"], data["team"], data.get("number", 0),
                data["rarity"], data["price"],
                RARITIES.get(data["rarity"], {}).get("rating", 10),
                2026, data.get("image", "")
            ))
        
        for winner in WINNERS:
            code = f"WIN_{winner['driver'][:3].upper()}_{winner['year']}"
            await db.execute("""
                INSERT OR IGNORE INTO cards 
                (code, name, team, number, rarity, price, rating_points, year, image)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                code, winner["driver"], "Indy 500 Winner", 0,
                winner.get("rarity", "INDY_EDITION"), winner.get("price", 500),
                RARITIES.get(winner.get("rarity", "INDY_EDITION"), {}).get("rating", 100),
                winner["year"], ""
            ))
        
        await db.commit()
    logger.info("✅ Данные загружены")

# ============================================================
# DB HELPER ФУНКЦИИ (АСИНХРОННЫЕ)
# ============================================================

async def get_user(user_id: int) -> Optional[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()

async def create_user(user_id: int, username: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        name = username or f"User{user_id}"
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, display_name) VALUES (?, ?, ?)",
            (user_id, username, name)
        )
        await db.commit()

async def update_balance(user_id: int, amount: int, tx_type: str = "unknown", code: str = None) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            new_balance = row[0]
        await db.execute(
            "INSERT INTO transactions (user_id, type, code, amount, balance_after) VALUES (?, ?, ?, ?, ?)",
            (user_id, tx_type, code, amount, new_balance)
        )
        await db.commit()
        return new_balance

async def get_user_cards(user_id: int) -> Dict[str, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code, quantity FROM user_cards WHERE user_id = ?", (user_id,)) as cursor:
            rows = await cursor.fetchall()
            return {row[0]: row[1] for row in rows}

async def get_card_info(code: str) -> Optional[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM cards WHERE code = ?", (code,)) as cursor:
            return await cursor.fetchone()

async def add_card_to_user(user_id: int, code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """INSERT INTO user_cards (user_id, code, quantity) VALUES (?, ?, 1) 
               ON CONFLICT(user_id, code) DO UPDATE SET quantity = quantity + 1""",
            (user_id, code)
        )
        await db.commit()

async def remove_card_from_user(user_id: int, code: str) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE user_cards SET quantity = quantity - 1 WHERE user_id = ? AND code = ?", (user_id, code))
        await db.execute("DELETE FROM user_cards WHERE user_id = ? AND code = ? AND quantity <= 0", (user_id, code))
        await db.commit()

async def get_game_attempts(user_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT game_attempts FROM users WHERE user_id = ?", (user_id,)) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 3

async def use_game_attempt(user_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET game_attempts = game_attempts - 1 WHERE user_id = ?", (user_id,))
        await db.commit()

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def get_rarity_emoji(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("emoji", "🟢")

def get_rarity_name(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("name", "Обычная")

# ============================================================
# РЫНОЧНЫЙ ДВИЖОК (АСИНХРОННЫЙ)
# ============================================================

class MarketEngine:
    @staticmethod
    async def update_all_prices() -> Dict[str, Any]:
        today = datetime.now().date()
        
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute("SELECT last_update FROM market_state WHERE id = 1") as cursor:
                row = await cursor.fetchone()
                if row and row[0] == today:
                    return {"status": "already_updated"}
            
            async with db.execute("SELECT code, price, rarity FROM cards") as cursor:
                cards = await cursor.fetchall()
            
            changes = {}
            
            for code, price, rarity in cards:
                race_factor = await MarketEngine._get_race_factor(db, code)
                demand_factor = await MarketEngine._get_demand_factor(db, code)
                rarity_factor = await MarketEngine._get_rarity_factor(db, rarity, code)
                volatility = random.uniform(-5, 5)
                
                total_change = race_factor + demand_factor + rarity_factor + volatility
                total_change = max(-30, min(50, total_change))
                
                new_price = int(price * (1 + total_change / 100))
                new_price = max(10, min(new_price, 100000))
                
                await db.execute(
                    "UPDATE cards SET price = ?, change_24h = ? WHERE code = ?",
                    (new_price, round(total_change, 1), code)
                )
                
                await db.execute(
                    """INSERT INTO price_history 
                       (card_code, price, change_percent, change_reason)
                       VALUES (?, ?, ?, ?)""",
                    (code, new_price, round(total_change, 1),
                     await MarketEngine._get_change_reason(total_change, race_factor, demand_factor, rarity_factor))
                )
                
                changes[code] = {"old_price": price, "new_price": new_price, "change": round(total_change, 1)}
            
            await db.execute(
                "INSERT OR REPLACE INTO market_state (id, last_update, market_data) VALUES (1, ?, ?)",
                (today, json.dumps(changes))
            )
            await db.commit()
            
            return {"status": "success", "changes": changes}
    
    @staticmethod
    async def _get_race_factor(db, card_code: str) -> float:
        async with db.execute("SELECT race_data FROM race_events ORDER BY date DESC LIMIT 3") as cursor:
            races = await cursor.fetchall()
        
        if not races:
            return 0
        
        total = 0
        for race in races:
            data = json.loads(race[0])
            if card_code == data.get("winner"):
                total += 25
            elif card_code in data.get("podium", []):
                total += 15
            elif card_code == data.get("pole"):
                total += 10
            elif card_code in data.get("dnf", []):
                total -= 15
        
        return max(-20, min(35, total))
    
    @staticmethod
    async def _get_demand_factor(db, card_code: str) -> float:
        async with db.execute(
            """SELECT COUNT(*) FROM transactions 
               WHERE code = ? AND type IN ('market_buy', 'buy')
               AND timestamp > datetime('now', '-7 days')""",
            (card_code,)
        ) as cursor:
            sales = (await cursor.fetchone())[0]
        
        async with db.execute(
            "SELECT COUNT(*) FROM market_listings WHERE card_code = ? AND status = 'active'",
            (card_code,)
        ) as cursor:
            listings = (await cursor.fetchone())[0]
        
        demand = 0
        if sales >= 50:
            demand += 20
        elif sales >= 25:
            demand += 10
        elif sales >= 10:
            demand += 5
        
        if listings == 0 and sales > 0:
            demand += 15
        elif listings <= 2:
            demand += 8
        elif listings > 20:
            demand -= 10
        elif listings > 50:
            demand -= 20
        
        return max(-25, min(35, demand))
    
    @staticmethod
    async def _get_rarity_factor(db, rarity: str, card_code: str) -> float:
        bonuses = {"REGULAR": 0, "RARE": 2, "EXCLUSIVE": 5, "LEGENDARY": 10, "INDY_EDITION": 15, "ULTIMATE": 20}
        base = bonuses.get(rarity, 0)
        
        async with db.execute("SELECT SUM(quantity) FROM user_cards WHERE code = ?", (card_code,)) as cursor:
            total = (await cursor.fetchone())[0] or 0
        
        if total < 10:
            scarcity = 15
        elif total < 50:
            scarcity = 10
        elif total < 100:
            scarcity = 5
        else:
            scarcity = 0
        
        return base + scarcity
    
    @staticmethod
    async def _get_change_reason(total: float, race: float, demand: float, rarity: float) -> str:
        parts = []
        if race > 10:
            parts.append("🏆 Отличные результаты")
        elif race > 5:
            parts.append("🏁 Хорошие результаты")
        elif race < -10:
            parts.append("💥 Плохие результаты")
        
        if demand > 15:
            parts.append("🔥 Высокий спрос")
        elif demand > 5:
            parts.append("📊 Средний спрос")
        elif demand < -10:
            parts.append("❌ Низкий спрос")
        
        if rarity > 10:
            parts.append("💎 Редкая карта")
        
        return ", ".join(parts) if parts else "🔄 Рыночная волатильность"

# ============================================================
# ПРОМОКОДЫ
# ============================================================

async def create_promo(reward_type: str, reward_value: str, max_uses: int, admin_id: int) -> str:
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO promocodes (code, reward_type, reward_value, max_uses, created_by) VALUES (?, ?, ?, ?, ?)",
            (code, reward_type, reward_value, max_uses, admin_id)
        )
        await db.commit()
    return code

async def use_promo(code: str, user_id: int) -> Dict[str, str]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM promo_usage WHERE code = ? AND user_id = ?", (code, user_id)) as cursor:
            if await cursor.fetchone():
                return {"status": "error", "message": "❌ Ты уже активировал этот промокод"}
        
        async with db.execute("SELECT reward_type, reward_value, max_uses, used FROM promocodes WHERE code = ?", (code,)) as cursor:
            row = await cursor.fetchone()
        
        if not row:
            return {"status": "error", "message": "❌ Промокод не найден"}
        
        reward_type, reward_value, max_uses, used = row
        if used >= max_uses:
            return {"status": "error", "message": "❌ Промокод использован"}
        
        if reward_type == "coins":
            amount = int(reward_value)
            await update_balance(user_id, amount, "promo")
            result = {"status": "success", "message": f"✅ Получено {amount} 💰"}
        else:
            card_code = reward_value
            await add_card_to_user(user_id, card_code)
            card = await get_card_info(card_code)
            result = {"status": "success", "message": f"✅ Получена карта {card[1]} ({card[0]})"}
        
        await db.execute("UPDATE promocodes SET used = used + 1 WHERE code = ?", (code,))
        await db.execute("INSERT INTO promo_usage (code, user_id) VALUES (?, ?)", (code, user_id))
        await db.commit()
        return result

# ============================================================
# ЕЖЕДНЕВНЫЙ БОНУС
# ============================================================

async def get_daily_bonus(user_id: int) -> Optional[Dict[str, Any]]:
    today = datetime.now().date()
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT 1 FROM daily_bonus WHERE user_id = ? AND date = ?", (user_id, today)) as cursor:
            if await cursor.fetchone():
                return None
        
        async with db.execute("SELECT streak FROM daily_bonus WHERE user_id = ? AND date = ?", 
                            (user_id, today - timedelta(days=1))) as cursor:
            row = await cursor.fetchone()
            streak = row[0] + 1 if row else 1
        
        bonus = 50 + (streak - 1) * 10
        if streak >= 7:
            bonus += 100
        
        await db.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))
        async with db.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,)) as cursor:
            new_balance = (await cursor.fetchone())[0]
        
        await db.execute(
            "INSERT INTO daily_bonus (user_id, date, streak, bonus) VALUES (?, ?, ?, ?)",
            (user_id, today, streak, bonus)
        )
        await db.execute(
            "INSERT INTO transactions (user_id, type, amount, balance_after) VALUES (?, 'daily_bonus', ?, ?)",
            (user_id, bonus, new_balance)
        )
        await db.commit()
        
        return {"bonus": bonus, "streak": streak}

# ============================================================
# КЛАВИАТУРЫ
# ============================================================

def main_menu(user_id: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    
    builder.button(text="🎴 Мои карты", callback_data="my_cards")
    builder.button(text="🎲 Получить карту", callback_data="get_card")
    builder.button(text="🏦 Биржа", callback_data="exchange")
    builder.button(text="📊 Рынок", callback_data="player_market")
    builder.button(text="👤 Профиль", callback_data="profile")
    builder.button(text="🏪 Магазин", callback_data="shop")
    builder.button(text="🎁 Бонус", callback_data="daily_bonus")
    builder.button(text="⚔️ PvP", callback_data="pvp_menu")
    builder.button(text="🎁 Промокод", callback_data="promo_enter")
    builder.button(text="ℹ️ О проекте", callback_data="about")
    
    if user_id and is_admin(user_id):
        builder.button(text="👑 INDY Admin", callback_data="admin_panel")
    
    builder.adjust(2, 2, 2, 2, 2, 1)
    return builder.as_markup()

def back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def admin_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📊 Обновить цены", callback_data="admin_update_prices")
    builder.button(text="🏁 Добавить гонку", callback_data="admin_add_race")
    builder.button(text="💰 Управление ценами", callback_data="admin_price")
    builder.button(text="🎁 Создать промокод", callback_data="admin_promo")
    builder.button(text="🎴 Все карты", callback_data="admin_all_cards")
    builder.button(text="📊 Статистика", callback_data="admin_stats")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 2, 2, 1)
    return builder.as_markup()

def shop_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Попытка (50 💰)", callback_data="shop_attempt")
    builder.button(text="🎴 Случайная карта (100 💰)", callback_data="shop_card")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

def pvp_bet_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Деньги", callback_data="pvp_bet_money")
    builder.button(text="🎴 Карта", callback_data="pvp_bet_card")
    builder.button(text="🔙 Назад", callback_data="pvp_menu")
    builder.adjust(2)
    return builder.as_markup()

def pvp_money_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="10 💰", callback_data="pvp_money_10")
    builder.button(text="25 💰", callback_data="pvp_money_25")
    builder.button(text="50 💰", callback_data="pvp_money_50")
    builder.button(text="100 💰", callback_data="pvp_money_100")
    builder.button(text="🔙 Назад", callback_data="pvp_menu")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def admin_promo_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="💎 Карта", callback_data="admin_promo_card")
    builder.button(text="💰 Монеты", callback_data="admin_promo_coins")
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(2)
    return builder.as_markup()

# ============================================================
# РОУТЕР
# ============================================================

router = Router()

# ============================================================
# ОБРАБОТЧИКИ (COMMANDS)
# ============================================================

@router.message(Command("start"))
async def cmd_start(message: Message) -> None:
    """Обработчик /start"""
    await create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "🏁 **IndyCard Exchange**\n\n"
        "💰 Баланс: 500 💰\n"
        "🎲 Попыток: 3/3ч\n\n"
        "Выбирай действие:",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

# ============================================================
# ОБРАБОТЧИКИ (CALLBACK) — ОБЩИЕ
# ============================================================

@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🏁 **Главное меню**",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "ℹ️ **IndyCard Exchange**\n\n"
        "🎴 Собирай карты пилотов IndyCar\n"
        "🏦 Торгуй на бирже и рынке\n"
        "⚔️ Играй в PvP на кубиках\n\n"
        "Разработчики: @Scanialove, @Gabriella1488",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "promo_enter")
async def cb_promo_enter(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🎁 **Введите промокод**\n\nОтправь код в сообщении (8 символов)",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(F.text.regexp(r"^[A-Z0-9]{8}$"))
async def handle_promo_code(message: Message) -> None:
    """Обработка ввода промокода"""
    result = await use_promo(message.text.upper(), message.from_user.id)
    await message.answer(f"🎁 **Результат**\n\n{result['message']}", parse_mode="Markdown")

# ============================================================
# ОБРАБОТЧИКИ — КАРТЫ
# ============================================================

@router.callback_query(F.data == "my_cards")
async def cb_my_cards(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cards = await get_user_cards(user_id)
    
    if not cards:
        await callback.message.edit_text("📭 Нет карт", reply_markup=back_button())
        await callback.answer()
        return
    
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, 
                    "EXCLUSIVE": 3, "RARE": 4, "REGULAR": 5}
    
    # Получаем информацию о каждой карте асинхронно
    card_infos = []
    for code, qty in cards.items():
        card = await get_card_info(code)
        if card:
            card_infos.append((code, qty, card))
    
    card_infos.sort(key=lambda x: rarity_order.get(x[2][4], 99))
    
    page = user_card_pages.get(user_id, 0)
    total_pages = (len(card_infos) + 4) // 5
    if page >= total_pages:
        page = max(0, total_pages - 1)
        user_card_pages[user_id] = page
    
    start = page * 5
    end = start + 5
    page_cards = card_infos[start:end]
    
    text = "🎴 **Мои карты**\n\n"
    for code, qty, card in page_cards:
        emoji = get_rarity_emoji(card[4])
        text += f"{emoji} {card[1]} ({code}) ×{qty}\n"
    text += f"\n📊 Всего: {sum(cards.values())} карт"
    if total_pages > 1:
        text += f"\n📄 Страница {page+1} из {total_pages}"
    
    builder = InlineKeyboardBuilder()
    if total_pages > 1:
        builder.button(text="◀️", callback_data=CardCallback(action="cards", page=page-1).pack())
        builder.button(text=f"{page+1}/{total_pages}", callback_data="cards_page")
        builder.button(text="▶️", callback_data=CardCallback(action="cards", page=page+1).pack())
        builder.adjust(3)
    
    builder.button(text="💸 Продать", callback_data="sell_menu")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(3, 2)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(CardCallback.filter(F.action == "cards"))
async def cb_cards_pagination(callback: CallbackQuery, callback_data: CardCallback) -> None:
    user_id = callback.from_user.id
    user_card_pages[user_id] = callback_data.page
    await cb_my_cards(callback)

@router.callback_query(F.data == "get_card")
async def cb_get_card(callback: CallbackQuery) -> None:
    rarities = [r for r, d in RARITIES.items() for _ in range(d["chance"])]
    rarity = random.choice(rarities)
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,)) as cursor:
            row = await cursor.fetchone()
    
    if not row:
        await callback.answer("❌ Нет карт", show_alert=True)
        return
    
    code = row[0]
    await add_card_to_user(callback.from_user.id, code)
    card = await get_card_info(code)
    
    await callback.message.edit_text(
        f"🎲 **Получена карта!**\n\n"
        f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {get_rarity_name(card[4])}\n"
        f"💰 {card[5]} 💰",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — ПРОДАЖА
# ============================================================

@router.callback_query(F.data == "sell_menu")
async def cb_sell_menu(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cards = await get_user_cards(user_id)
    
    if not cards:
        await callback.message.edit_text("📭 Нет карт для продажи", reply_markup=back_button())
        await callback.answer()
        return
    
    card_list = list(cards.keys())
    user_sell_session[user_id] = {"cards": card_list, "index": 0}
    await show_sell_card(callback.message, user_id, callback)

async def show_sell_card(message: Message, user_id: int, callback: Optional[CallbackQuery] = None) -> None:
    session = user_sell_session.get(user_id)
    if not session:
        return
    
    index = session["index"]
    cards = session["cards"]
    if index >= len(cards):
        index = 0
        session["index"] = 0
    
    code = cards[index]
    card = await get_card_info(code)
    if not card:
        return
    
    user_cards = await get_user_cards(user_id)
    qty = user_cards.get(code, 0)
    price = int(card[5] * 0.7)
    total = len(cards)
    emoji = get_rarity_emoji(card[4])
    
    builder = InlineKeyboardBuilder()
    builder.button(text="◀️", callback_data=CardCallback(action="sell_prev", code=code).pack())
    builder.button(text=f"{index+1}/{total}", callback_data="sell_count")
    builder.button(text="▶️", callback_data=CardCallback(action="sell_next", code=code).pack())
    builder.button(text=f"💰 Продать за {price} 💰", callback_data=CardCallback(action="sell_confirm", code=code).pack())
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(3, 1, 1)
    
    await message.edit_text(
        f"💵 **Продажа карты**\n\n"
        f"{emoji} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {get_rarity_name(card[4])}\n"
        f"💰 Цена: {card[5]} 💰\n"
        f"💸 Продажа за: {price} 💰\n"
        f"📦 Количество: {qty}\n\n"
        f"Карта {index+1} из {total}",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    if callback:
        await callback.answer()

@router.callback_query(CardCallback.filter(F.action == "sell_next"))
async def cb_sell_next(callback: CallbackQuery, callback_data: CardCallback) -> None:
    user_id = callback.from_user.id
    if user_id not in user_sell_session:
        await callback.answer("❌ Сессия истекла")
        return
    user_sell_session[user_id]["index"] += 1
    await show_sell_card(callback.message, user_id, callback)
    await callback.answer()

@router.callback_query(CardCallback.filter(F.action == "sell_prev"))
async def cb_sell_prev(callback: CallbackQuery, callback_data: CardCallback) -> None:
    user_id = callback.from_user.id
    if user_id not in user_sell_session:
        await callback.answer("❌ Сессия истекла")
        return
    user_sell_session[user_id]["index"] -= 1
    if user_sell_session[user_id]["index"] < 0:
        user_sell_session[user_id]["index"] = 0
    await show_sell_card(callback.message, user_id, callback)
    await callback.answer()

@router.callback_query(CardCallback.filter(F.action == "sell_confirm"))
async def cb_sell_confirm(callback: CallbackQuery, callback_data: CardCallback) -> None:
    code = callback_data.code
    user_id = callback.from_user.id
    
    card = await get_card_info(code)
    if not card:
        await callback.answer("❌ Карта не найдена")
        return
    
    user_cards = await get_user_cards(user_id)
    if user_cards.get(code, 0) < 1:
        await callback.answer("❌ У тебя нет этой карты")
        return
    
    price = int(card[5] * 0.7)
    await remove_card_from_user(user_id, code)
    new_balance = await update_balance(user_id, price, "sell", code)
    
    await callback.message.edit_text(
        f"✅ {card[1]} ({code}) продана за {price} 💰\n"
        f"💰 Новый баланс: {new_balance} 💰",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — БИРЖА
# ============================================================

@router.callback_query(F.data == "exchange")
async def cb_exchange(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT code, name, rarity, price, change_24h FROM cards ORDER BY price DESC LIMIT 15"
        ) as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        await callback.message.edit_text("📭 Нет карт", reply_markup=back_button())
        await callback.answer()
        return
    
    text = f"🏦 **Биржа**\n\n💰 Баланс: {user['balance']} 💰\n\n"
    for code, name, rarity, price, change in rows:
        emoji = get_rarity_emoji(rarity)
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        text += f"{emoji} {name} ({code}) — {price} 💰 {arrow} {change}%\n"
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Обновить цены", callback_data="exchange_refresh")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)
    
    for code, name, rarity, price, change in rows[:5]:
        builder.button(text=f"💎 {name} ({code}) — {price} 💰", callback_data=f"buy_{code}")
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "exchange_refresh")
async def cb_exchange_refresh(callback: CallbackQuery) -> None:
    result = await MarketEngine.update_all_prices()
    
    if result["status"] == "already_updated":
        await callback.answer("⏰ Цены уже обновлены сегодня!")
    else:
        await callback.answer("🔄 Цены обновлены!")
    await cb_exchange(callback)

@router.callback_query(F.data.startswith("buy_"))
async def cb_buy_card(callback: CallbackQuery) -> None:
    code = callback.data.replace("buy_", "")
    user_id = callback.from_user.id
    
    card = await get_card_info(code)
    if not card:
        await callback.answer("❌ Карта не найдена")
        return
    
    user = await get_user(user_id)
    if user["balance"] < card[5]:
        await callback.answer(f"❌ Нужно {card[5]} 💰", show_alert=True)
        return
    
    new_balance = await update_balance(user_id, -card[5], "buy", code)
    await add_card_to_user(user_id, code)
    
    await callback.message.edit_text(
        f"✅ {card[1]} ({code}) куплена за {card[5]} 💰\n"
        f"💰 Новый баланс: {new_balance} 💰",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — РЫНОК ИГРОКОВ
# ============================================================

@router.callback_query(F.data == "player_market")
async def cb_player_market(callback: CallbackQuery) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, user_id, card_code, price FROM market_listings WHERE status = 'active'"
        ) as cursor:
            listings = await cursor.fetchall()
    
    if not listings:
        await callback.message.edit_text(
            "📊 **Рынок игроков**\n\nНа рынке пока нет карт.",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    text = "📊 **Рынок игроков**\n\n"
    builder = InlineKeyboardBuilder()
    
    for listing_id, user_id, card_code, price in listings:
        card = await get_card_info(card_code)
        if not card:
            continue
        seller = await get_user(user_id)
        seller_name = seller["username"] or seller["display_name"] or "Неизвестно"
        emoji = get_rarity_emoji(card[4])
        text += f"{emoji} {card[1]} ({card[0]}) — {price} 💰 (от @{seller_name})\n"
        builder.button(
            text=f"💎 Купить {card[1]} за {price} 💰",
            callback_data=MarketCallback(action="buy", listing_id=listing_id, card_code=card_code).pack()
        )
    
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(MarketCallback.filter(F.action == "buy"))
async def cb_market_buy(callback: CallbackQuery, callback_data: MarketCallback) -> None:
    listing_id = callback_data.listing_id
    buyer_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id, card_code, price FROM market_listings WHERE id = ? AND status = 'active'",
            (listing_id,)
        ) as cursor:
            row = await cursor.fetchone()
    
    if not row:
        await callback.answer("❌ Карта уже продана", show_alert=True)
        return
    
    seller_id, card_code, price = row
    
    if buyer_id == seller_id:
        await callback.answer("❌ Нельзя купить свою карту", show_alert=True)
        return
    
    buyer = await get_user(buyer_id)
    if buyer["balance"] < price:
        await callback.answer(f"❌ Нужно {price} 💰", show_alert=True)
        return
    
    seller_cards = await get_user_cards(seller_id)
    if seller_cards.get(card_code, 0) < 1:
        await callback.answer("❌ У продавца больше нет этой карты", show_alert=True)
        return
    
    await update_balance(buyer_id, -price, "market_buy", card_code)
    await update_balance(seller_id, price, "market_sell", card_code)
    await remove_card_from_user(seller_id, card_code)
    await add_card_to_user(buyer_id, card_code)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE market_listings SET status = 'sold' WHERE id = ?", (listing_id,))
        await db.commit()
    
    await callback.message.edit_text(
        f"✅ Покупка совершена!\n\nКарта {card_code} куплена за {price} 💰",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — МАГАЗИН
# ============================================================

@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "🏪 **Магазин**\n\n"
        "🎲 Попытка в игру — 50 💰\n"
        "🎴 Случайная карта — 100 💰",
        reply_markup=shop_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "shop_attempt")
async def cb_shop_attempt(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    if user["balance"] < 50:
        await callback.answer("❌ Нужно 50 💰", show_alert=True)
        return
    
    await update_balance(callback.from_user.id, -50, "shop")
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE users SET game_attempts = game_attempts + 1 WHERE user_id = ?", (callback.from_user.id,))
        await db.commit()
    
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"✅ Попытка куплена!\n"
        f"🎲 Попыток: {user['game_attempts']}\n"
        f"💰 Баланс: {user['balance']} 💰",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "shop_card")
async def cb_shop_card(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    if user["balance"] < 100:
        await callback.answer("❌ Нужно 100 💰", show_alert=True)
        return
    
    await update_balance(callback.from_user.id, -100, "shop")
    
    rarities = [r for r, d in RARITIES.items() for _ in range(d["chance"])]
    rarity = random.choice(rarities)
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,)) as cursor:
            row = await cursor.fetchone()
    
    if row:
        code = row[0]
        await add_card_to_user(callback.from_user.id, code)
        card = await get_card_info(code)
        await callback.message.edit_text(
            f"🎴 Куплена карта!\n\n"
            f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
    else:
        await callback.message.edit_text("❌ Нет карт", reply_markup=back_button())
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — ПРОФИЛЬ
# ============================================================

@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery) -> None:
    user = await get_user(callback.from_user.id)
    cards = await get_user_cards(callback.from_user.id)
    total = sum(cards.values())
    attempts = await get_game_attempts(callback.from_user.id)
    
    await callback.message.edit_text(
        f"👤 **Профиль**\n\n"
        f"Имя: {user['username'] or user['display_name']}\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎴 Карт: {total}\n"
        f"🏆 Рейтинг: {user['rating']}\n"
        f"🎲 Попыток: {attempts}",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — ЕЖЕДНЕВНЫЙ БОНУС
# ============================================================

@router.callback_query(F.data == "daily_bonus")
async def cb_daily_bonus(callback: CallbackQuery) -> None:
    result = await get_daily_bonus(callback.from_user.id)
    
    if not result:
        await callback.answer("❌ Ты уже получил бонус сегодня!", show_alert=True)
        return
    
    emoji = "🔥" if result["streak"] >= 7 else "🎁"
    user = await get_user(callback.from_user.id)
    await callback.message.edit_text(
        f"{emoji} **Ежедневный бонус!**\n\n"
        f"День {result['streak']} подряд\n"
        f"+{result['bonus']} 💰\n\n"
        f"💰 Баланс: {user['balance']} 💰",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — PVP
# ============================================================

@router.callback_query(F.data == "pvp_menu")
async def cb_pvp_menu(callback: CallbackQuery) -> None:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Создать битву", callback_data="pvp_create")
    builder.button(text="📋 Список битв", callback_data="pvp_list")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2)
    
    await callback.message.edit_text(
        "⚔️ **PvP Кубики**\n\nСоздай битву или присоединись к существующей.",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "pvp_create")
async def cb_pvp_create(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "⚔️ **Создание битвы**\n\nЧто ставишь?",
        reply_markup=pvp_bet_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "pvp_bet_money")
async def cb_pvp_bet_money(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "💰 **Ставка деньгами**\n\nВыбери сумму:",
        reply_markup=pvp_money_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data.startswith("pvp_money_"))
async def cb_pvp_money_create(callback: CallbackQuery) -> None:
    amount = int(callback.data.replace("pvp_money_", ""))
    user_id = callback.from_user.id
    
    user = await get_user(user_id)
    if user["balance"] < amount:
        await callback.answer(f"❌ Нужно {amount} 💰", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pvp_battles (player1_id, bet_type, bet_value, status) VALUES (?, 'money', ?, 'waiting')",
            (user_id, str(amount))
        )
        battle_id = db.lastrowid
        await db.commit()
    
    await callback.message.edit_text(
        f"⚔️ **Битва создана!**\n\nID: {battle_id}\nСтавка: {amount} 💰\n\nДай этот ID другу: `{battle_id}`",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "pvp_bet_card")
async def cb_pvp_bet_card(callback: CallbackQuery) -> None:
    user_id = callback.from_user.id
    cards = await get_user_cards(user_id)
    
    if not cards:
        await callback.message.edit_text("📭 Нет карт для ставки", reply_markup=back_button())
        await callback.answer()
        return
    
    builder = InlineKeyboardBuilder()
    for code, qty in cards.items():
        card = await get_card_info(code)
        if card:
            builder.button(
                text=f"{get_rarity_emoji(card[4])} {card[1]} ×{qty}",
                callback_data=PvpCallback(action="card_bet", card_code=code).pack()
            )
    builder.button(text="🔙 Назад", callback_data="pvp_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "🎴 **Выбери карту для ставки**",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(PvpCallback.filter(F.action == "card_bet"))
async def cb_pvp_card_create(callback: CallbackQuery, callback_data: PvpCallback) -> None:
    user_id = callback.from_user.id
    code = callback_data.card_code
    
    cards = await get_user_cards(user_id)
    if cards.get(code, 0) < 1:
        await callback.answer("❌ У тебя нет этой карты", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO pvp_battles (player1_id, bet_type, bet_value, status) VALUES (?, 'card', ?, 'waiting')",
            (user_id, code)
        )
        battle_id = db.lastrowid
        await db.commit()
    
    card = await get_card_info(code)
    await callback.message.edit_text(
        f"⚔️ **Битва создана!**\n\nID: {battle_id}\nСтавка: карта {card[1]}\n\nДай этот ID другу: `{battle_id}`",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "pvp_list")
async def cb_pvp_list(callback: CallbackQuery) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, player1_id, bet_type, bet_value FROM pvp_battles WHERE status = 'waiting'"
        ) as cursor:
            rows = await cursor.fetchall()
    
    if not rows:
        await callback.message.edit_text("📭 Нет активных битв", reply_markup=back_button())
        await callback.answer()
        return
    
    text = "⚔️ **Активные битвы**\n\n"
    builder = InlineKeyboardBuilder()
    
    for battle_id, player1_id, bet_type, bet_value in rows:
        player = await get_user(player1_id)
        player_name = player["username"] or player["display_name"] or "Неизвестно"
        bet_text = f"{bet_value} 💰" if bet_type == "money" else f"карта {bet_value}"
        text += f"ID {battle_id}: @{player_name} ставит {bet_text}\n"
        builder.button(
            text=f"⚔️ Присоединиться к {battle_id}",
            callback_data=PvpCallback(action="join", battle_id=battle_id).pack()
        )
    
    builder.button(text="🔙 Назад", callback_data="pvp_menu")
    builder.adjust(1)
    
    await callback.message.edit_text(text, reply_markup=builder.as_markup(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(PvpCallback.filter(F.action == "join"))
async def cb_pvp_join(callback: CallbackQuery, callback_data: PvpCallback) -> None:
    battle_id = callback_data.battle_id
    player2_id = callback.from_user.id
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT player1_id, bet_type, bet_value FROM pvp_battles WHERE id = ? AND status = 'waiting'",
            (battle_id,)
        ) as cursor:
            battle = await cursor.fetchone()
    
    if not battle:
        await callback.answer("❌ Битва не найдена", show_alert=True)
        return
    
    player1_id, bet_type, bet_value = battle
    
    if player1_id == player2_id:
        await callback.answer("❌ Нельзя присоединиться к своей битве", show_alert=True)
        return
    
    # Проверяем ставку
    if bet_type == "money":
        amount = int(bet_value)
        user2 = await get_user(player2_id)
        if user2["balance"] < amount:
            await callback.answer(f"❌ Нужно {amount} 💰", show_alert=True)
            return
    else:
        user2_cards = await get_user_cards(player2_id)
        if user2_cards.get(bet_value, 0) < 1:
            await callback.answer("❌ У тебя нет этой карты", show_alert=True)
            return
    
    # Обновляем битву
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE pvp_battles SET player2_id = ?, status = 'active' WHERE id = ?", (player2_id, battle_id))
        await db.commit()
    
    # Кидаем кубики
    d1_p1, d2_p1 = random.randint(1, 6), random.randint(1, 6)
    d1_p2, d2_p2 = random.randint(1, 6), random.randint(1, 6)
    total_p1 = d1_p1 + d2_p1
    total_p2 = d1_p2 + d2_p2
    
    if total_p1 > total_p2:
        winner_id = player1_id
    elif total_p2 > total_p1:
        winner_id = player2_id
    else:
        winner_id = None
    
    # Передаём ставку
    if winner_id:
        if bet_type == "money":
            amount = int(bet_value)
            loser_id = player2_id if winner_id == player1_id else player1_id
            await update_balance(loser_id, -amount, "pvp_loss")
            await update_balance(winner_id, amount, "pvp_win")
        else:
            loser_id = player2_id if winner_id == player1_id else player1_id
            await remove_card_from_user(loser_id, bet_value)
            await add_card_to_user(winner_id, bet_value)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "UPDATE pvp_battles SET status = 'finished', winner_id = ? WHERE id = ?",
            (winner_id, battle_id)
        )
        await db.commit()
    
    await callback.message.edit_text(
        f"⚔️ **Результат битвы {battle_id}**\n\n"
        f"Игрок 1: {d1_p1} + {d2_p1} = {total_p1}\n"
        f"Игрок 2: {d1_p2} + {d2_p2} = {total_p2}\n\n"
        f"{'🏆 Победил Игрок 1!' if winner_id == player1_id else '🏆 Победил Игрок 2!' if winner_id else '🤝 Ничья!'}",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ОБРАБОТЧИКИ — АДМИНКА
# ============================================================

@router.callback_query(F.data == "admin_panel")
async def cb_admin_panel(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "👑 **INDY Admin**\n\n🏁 **Админ-панель**\n\nВыберите действие:",
        reply_markup=admin_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_update_prices")
async def cb_admin_update_prices(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text("🔄 **Обновление цен...**", parse_mode="Markdown")
    
    result = await MarketEngine.update_all_prices()
    
    if result["status"] == "already_updated":
        await callback.message.edit_text(
            "⏰ **Цены уже обновлены сегодня!**",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    changes = result.get("changes", {})
    sorted_changes = sorted(changes.items(), key=lambda x: x[1]["change"], reverse=True)
    
    text = "📊 **Обновление цен завершено!**\n\n"
    text += "📈 **Топ-5 выросших:**\n"
    for code, data in sorted_changes[:5]:
        if data["change"] > 0:
            text += f"✅ {code}: {data['old_price']} → {data['new_price']} (+{data['change']}%)\n"
    
    text += "\n📉 **Топ-5 упавших:**\n"
    for code, data in sorted_changes[-5:]:
        if data["change"] < 0:
            text += f"❌ {code}: {data['old_price']} → {data['new_price']} ({data['change']}%)\n"
    
    text += f"\n📊 Изменено: {len(changes)} карт"
    
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_all_cards")
async def cb_admin_all_cards(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT code, name, rarity, price 
            FROM cards 
            ORDER BY 
                CASE rarity 
                    WHEN 'ULTIMATE' THEN 1
                    WHEN 'INDY_EDITION' THEN 2
                    WHEN 'LEGENDARY' THEN 3
                    WHEN 'EXCLUSIVE' THEN 4
                    WHEN 'RARE' THEN 5
                    WHEN 'REGULAR' THEN 6
                END,
                price DESC
        """) as cursor:
            cards = await cursor.fetchall()
    
    text = "💎 **Все карты**\n\n"
    current_rarity = None
    
    for code, name, rarity, price in cards:
        if rarity != current_rarity:
            current_rarity = rarity
            emoji = get_rarity_emoji(rarity)
            text += f"\n{emoji} **{get_rarity_name(rarity)}**\n"
        text += f"  • {name} ({code}) — {price} 💰\n"
    
    if len(text) > 4000:
        text = text[:4000] + "\n\n... и ещё карты"
    
    await callback.message.edit_text(text, reply_markup=back_button(), parse_mode="Markdown")
    await callback.answer()

@router.callback_query(F.data == "admin_stats")
async def cb_admin_stats(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM users") as cursor:
            users = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM cards") as cursor:
            cards = (await cursor.fetchone())[0]
        async with db.execute("SELECT SUM(quantity) FROM user_cards") as cursor:
            total = (await cursor.fetchone())[0] or 0
        async with db.execute("SELECT SUM(balance) FROM users") as cursor:
            total_balance = (await cursor.fetchone())[0] or 0
        async with db.execute("SELECT COUNT(*) FROM market_listings WHERE status = 'active'") as cursor:
            listings = (await cursor.fetchone())[0]
        async with db.execute("SELECT COUNT(*) FROM pvp_battles WHERE status = 'finished'") as cursor:
            battles = (await cursor.fetchone())[0]
    
    await callback.message.edit_text(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {users}\n"
        f"🎴 Карт: {cards}\n"
        f"📦 У игроков: {total}\n"
        f"💰 Всего монет: {total_balance}\n"
        f"📊 Активных лотов: {listings}\n"
        f"⚔️ PvP битв: {battles}",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_promo")
async def cb_admin_promo_start(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🎁 **Создание промокода**\n\nЧто будет наградой?",
        reply_markup=admin_promo_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_promo_card")
async def cb_admin_promo_card(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code, name, rarity FROM cards ORDER BY price DESC LIMIT 20") as cursor:
            rows = await cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for code, name, rarity in rows:
        builder.button(
            text=f"{get_rarity_emoji(rarity)} {name} ({code})",
            callback_data=AdminCallback(action="promo_card", card_code=code).pack()
        )
    builder.button(text="🔙 Назад", callback_data="admin_promo")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "🎁 **Выбери карту для промокода**",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_promo_coins")
async def cb_admin_promo_coins(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        return
    
    await callback.message.edit_text(
        "💵 **Введите сумму монет**\n\nОтправь число в сообщении",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(F.text.regexp(r"^\d+$"))
async def handle_admin_promo_coins(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    amount = int(message.text.strip())
    code = await create_promo("coins", str(amount), 10, message.from_user.id)
    await message.answer(
        f"🎁 **Промокод создан!**\n\n"
        f"Код: `{code}`\n"
        f"Награда: {amount} 💰\n"
        f"Активаций: 10",
        parse_mode="Markdown"
    )

@router.callback_query(AdminCallback.filter(F.action == "promo_card"))
async def cb_admin_promo_card_create(callback: CallbackQuery, callback_data: AdminCallback) -> None:
    if not is_admin(callback.from_user.id):
        return
    
    card_code = callback_data.card_code
    code = await create_promo("card", card_code, 5, callback.from_user.id)
    card = await get_card_info(card_code)
    
    await callback.message.edit_text(
        f"🎁 **Промокод создан!**\n\n"
        f"Код: `{code}`\n"
        f"Награда: {card[1]} ({card[0]})\n"
        f"Активаций: 5",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "admin_price")
async def cb_admin_price_menu(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT code, name, rarity, price FROM cards ORDER BY price DESC LIMIT 20") as cursor:
            rows = await cursor.fetchall()
    
    builder = InlineKeyboardBuilder()
    for code, name, rarity, price in rows:
        builder.button(
            text=f"{get_rarity_emoji(rarity)} {name} ({code}) — {price} 💰",
            callback_data=AdminCallback(action="price_edit", card_code=code).pack()
        )
    builder.button(text="🔙 Назад", callback_data="admin_panel")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "💰 **Управление ценами**\n\nВыбери карту:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(AdminCallback.filter(F.action == "price_edit"))
async def cb_admin_price_edit(callback: CallbackQuery, callback_data: AdminCallback) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    code = callback_data.card_code
    card = await get_card_info(code)
    if not card:
        await callback.answer("❌ Карта не найдена")
        return
    
    admin_price_session[callback.from_user.id] = code
    
    builder = InlineKeyboardBuilder()
    for change in [-100, -50, -10, 10, 50, 100]:
        sign = "🔽" if change < 0 else "🔼"
        builder.button(
            text=f"{sign} {change}",
            callback_data=AdminCallback(action="price_change", card_code=code, price_change=change).pack()
        )
    builder.button(text="🔙 Назад", callback_data="admin_price")
    builder.adjust(3, 3, 1)
    
    await callback.message.edit_text(
        f"💰 **Изменение цены**\n\n"
        f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n"
        f"Текущая цена: {card[5]} 💰\n\n"
        f"Выбери изменение:",
        reply_markup=builder.as_markup(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(AdminCallback.filter(F.action == "price_change"))
async def cb_admin_price_change(callback: CallbackQuery, callback_data: AdminCallback) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    code = admin_price_session.get(callback.from_user.id)
    if not code:
        await callback.answer("❌ Сессия истекла")
        return
    
    card = await get_card_info(code)
    if not card:
        await callback.answer("❌ Карта не найдена")
        return
    
    change = callback_data.price_change
    new_price = max(10, card[5] + change)
    
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE cards SET price = ? WHERE code = ?", (new_price, code))
        await db.commit()
    
    await callback.answer(f"✅ Цена изменена: {card[5]} → {new_price} 💰", show_alert=True)
    await cb_admin_price_menu(callback)

@router.callback_query(F.data == "admin_add_race")
async def cb_admin_add_race(callback: CallbackQuery) -> None:
    if not is_admin(callback.from_user.id):
        await callback.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await callback.message.edit_text(
        "🏁 **Добавление гонки**\n\n"
        "Введите данные в формате:\n"
        "`название|победитель|подиум|поул|dnf`\n\n"
        "Пример:\n"
        "`Indy500|PAL|NEW,OWA|DIX|ERI,GRO`",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(F.text.contains("|"))
async def handle_admin_add_race(message: Message) -> None:
    if not is_admin(message.from_user.id):
        return
    
    try:
        parts = message.text.strip().split("|")
        if len(parts) < 3:
            await message.answer("❌ Неверный формат. Используй: название|победитель|подиум|поул|dnf")
            return
        
        event_name = parts[0]
        winner = parts[1].strip()
        podium = [p.strip() for p in parts[2].split(",")] if len(parts) > 2 else []
        pole = parts[3].strip() if len(parts) > 3 else None
        dnf = [d.strip() for d in parts[4].split(",")] if len(parts) > 4 else []
        
        race_data = {
            "winner": winner,
            "podium": podium,
            "pole": pole,
            "dnf": dnf
        }
        
        async with aiosqlite.connect(DB_PATH) as db:
            await db.execute(
                "INSERT INTO race_events (date, event_name, race_data) VALUES (?, ?, ?)",
                (datetime.now().date(), event_name, json.dumps(race_data))
            )
            await db.commit()
        
        await MarketEngine.update_all_prices()
        
        await message.answer(
            f"✅ **Гонка добавлена!**\n\n"
            f"🏁 {event_name}\n"
            f"🏆 Победитель: {winner}\n"
            f"🥇 Подиум: {', '.join(podium)}\n"
            f"🏁 Поул: {pole}\n"
            f"💥 DNF: {', '.join(dnf) if dnf else '—'}\n\n"
            f"🔄 Цены обновлены!",
            parse_mode="Markdown"
        )
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")

# ============================================================
# ЗАПУСК
# ============================================================

async def on_startup() -> None:
    """Установка вебхука при старте"""
    await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    logger.info(f"✅ Вебхук установлен: {WEBHOOK_URL}{WEBHOOK_PATH}")

async def on_shutdown() -> None:
    """Удаление вебхука при остановке"""
    await bot.delete_webhook()
    logger.info("❌ Вебхук удалён")

def main() -> None:
    """Главная функция запуска"""
    if WEBHOOK_URL:
        logger.info(f"🚀 Запуск в режиме вебхука на порту {PORT}")
        
        app = web.Application()
        
        SimpleRequestHandler(
            dispatcher=dp,
            bot=bot,
        ).register(app, path=WEBHOOK_PATH)
        
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:
        logger.info("🚀 Запуск в режиме поллинга (локально)")
        dp.run_polling(bot)

if __name__ == "__main__":
    # Инициализация БД
    import asyncio
    asyncio.run(init_db())
    
    # Создаём бота и диспетчер
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    dp.include_router(router)
    
    main() 
