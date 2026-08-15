import os
import asyncio
import logging
import random
import sqlite3
from datetime import datetime
from contextlib import asynccontextmanager

from aiogram import Bot, Dispatcher, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from data.drivers import DRIVERS
from data.winners import WINNERS

# ===== LOGGING =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== CONFIG =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8000))
ADMIN_IDS = [7025868617, 7946032603]

# ===== RARITIES =====
RARITIES = {
    "REGULAR": {"emoji": "🟢", "rating": 10, "chance": 50},
    "RARE": {"emoji": "⭐", "rating": 25, "chance": 25},
    "EXCLUSIVE": {"emoji": "🔮", "rating": 40, "chance": 15},
    "LEGENDARY": {"emoji": "💎", "rating": 60, "chance": 7},
    "INDY_EDITION": {"emoji": "🏁", "rating": 100, "chance": 2},
    "ULTIMATE": {"emoji": "👑", "rating": 150, "chance": 1},
}

# ===== DATABASE =====
def init_db():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        display_name TEXT,
        balance INTEGER DEFAULT 500,
        rating INTEGER DEFAULT 0,
        pvp_wins INTEGER DEFAULT 0,
        pvp_losses INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        language TEXT DEFAULT 'ru'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        code TEXT,
        quantity INTEGER DEFAULT 1,
        acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(user_id, code)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS cards (
        code TEXT PRIMARY KEY,
        name TEXT,
        team TEXT,
        number INTEGER,
        rarity TEXT,
        price INTEGER,
        rating_points INTEGER DEFAULT 10,
        year INTEGER,
        image TEXT
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS transactions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        type TEXT,
        code TEXT,
        amount INTEGER,
        balance_after INTEGER,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS auctions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_code TEXT,
        seller_id INTEGER,
        start_price INTEGER,
        current_bid INTEGER,
        bidder_id INTEGER,
        end_time TIMESTAMP,
        status TEXT DEFAULT 'active'
    )""")
    conn.commit()
    conn.close()


def seed_data():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    for code, data in DRIVERS.items():
        c.execute("""INSERT OR IGNORE INTO cards (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, data["name"], data["team"], data["number"], data["rarity"], data["price"],
             RARITIES.get(data["rarity"], {}).get("rating", 10), data.get("year", 2026), data.get("image", "")))
    for name, data in WINNERS.items():
        code = f"WIN_{name[:3].upper()}_{data['year']}"
        c.execute("""INSERT OR IGNORE INTO cards (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, name, "Indy 500 Winner", 0, data["rarity"], data["price"],
             RARITIES.get(data["rarity"], {}).get("rating", 10), data["year"], ""))
    conn.commit()
    conn.close()


init_db()
seed_data()

# ===== DATABASE FUNCTIONS =====
def get_user(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"user_id": row[0], "username": row[1], "display_name": row[2], "balance": row[3], "rating": row[4],
                "pvp_wins": row[5], "pvp_losses": row[6], "created_at": row[7], "language": row[8]}
    return None


def create_user(user_id, username):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    display_name = username or f"User{user_id}"
    c.execute("INSERT OR IGNORE INTO users (user_id, username, display_name) VALUES (?, ?, ?)",
              (user_id, username, display_name))
    conn.commit()
    conn.close()
    return get_user(user_id)


def update_balance(user_id, amount, tx_type="unknown", code=None):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (amount, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = c.fetchone()[0]
    c.execute("INSERT INTO transactions (user_id, type, code, amount, balance_after) VALUES (?, ?, ?, ?, ?)",
              (user_id, tx_type, code, amount, new_balance))
    conn.commit()
    conn.close()
    return new_balance


def get_user_cards(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, quantity FROM user_cards WHERE user_id = ?", (user_id,))
    rows = c.fetchall()
    conn.close()
    return {row[0]: row[1] for row in rows}


def get_card_info(code):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT * FROM cards WHERE code = ?", (code,))
    row = c.fetchone()
    conn.close()
    if row:
        return {"code": row[0], "name": row[1], "team": row[2], "number": row[3], "rarity": row[4], "price": row[5],
                "rating": row[6], "year": row[7], "image": row[8]}
    return None


def add_card_to_user(user_id, code, quantity=1):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("""INSERT INTO user_cards (user_id, code, quantity) VALUES (?, ?, ?)
        ON CONFLICT(user_id, code) DO UPDATE SET quantity = quantity + ?""",
              (user_id, code, quantity, quantity))
    conn.commit()
    conn.close()


def remove_card_from_user(user_id, code, quantity=1):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE user_cards SET quantity = quantity - ? WHERE user_id = ? AND code = ?",
              (quantity, user_id, code))
    c.execute("DELETE FROM user_cards WHERE user_id = ? AND code = ? AND quantity <= 0", (user_id, code))
    conn.commit()
    conn.close()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def get_rarity_emoji(rarity):
    return RARITIES.get(rarity, {}).get("emoji", "🟢")


def get_rarity_rating(rarity):
    return RARITIES.get(rarity, {}).get("rating", 10)


# ===== KEYBOARDS (FIXED) =====
def main_menu():
    buttons = [
        [InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
         InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card")],
        [InlineKeyboardButton(text="🏦 Биржа", callback_data="exchange"),
         InlineKeyboardButton(text="🎮 Мини-игры", callback_data="games")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def back_to_menu():
    buttons = [[InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def games_menu():
    buttons = [
        [InlineKeyboardButton(text="🎲 Угадай пилота", callback_data="game_guess_driver")],
        [InlineKeyboardButton(text="🗺️ Угадай трассу", callback_data="game_guess_track")],
        [InlineKeyboardButton(text="🎲 Бросок кубиков", callback_data="game_dice")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def admin_panel():
    buttons = [
        [InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_add"),
         InlineKeyboardButton(text="📝 Редактировать карту", callback_data="admin_edit")],
        [InlineKeyboardButton(text="🗑️ Удалить карту", callback_data="admin_delete"),
         InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")],
    ]
    return InlineKeyboardMarkup(inline_keyboard=buttons)


# ===== HANDLERS =====
async def start_command(message: types.Message):
    user = create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        f"🏁 **IndyCard Exchange**\n\n"
        f"Добро пожаловать, {user['display_name']}!\n"
        f"💰 Баланс: {user['balance']} 💰\n\n"
        f"Используй кнопки для навигации:",
        reply_markup=main_menu(),
        parse_mode="Markdown",
    )


async def admin_command(message: types.Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("👑 **Админ-панель**", reply_markup=admin_panel(), parse_mode="Markdown")


async def setname_command(message: types.Message):
    parts = message.text.split(maxsplit=1)
    if len(parts) < 2:
        await message.answer("❌ Используй: /setname Твой ник")
        return
    new_name = parts[1].strip()
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET display_name = ? WHERE user_id = ?", (new_name, message.from_user.id))
    conn.commit()
    conn.close()
    await message.answer(f"✅ Твой ник изменён на: {new_name}")


# ... (здесь будут все остальные обработчики команд: callback_handler, buy, sell, balance, top, мини-игры, админ-функции) ...

# ===== WEBHOOK SETUP =====
async def on_startup(app: web.Application):
    bot = app["bot"]
    await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    logger.info(f"✅ Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")


async def on_shutdown(app: web.Application):
    logger.info("Shutting down...")


def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    
    # Регистрация хендлеров (нужно будет раскомментировать и добавить)
    # register_handlers(dp)

    app = web.Application()
    app["bot"] = bot

    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
