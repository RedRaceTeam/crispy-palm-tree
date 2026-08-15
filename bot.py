import os
import logging
import sqlite3
import random
import string
import asyncio
from datetime import datetime, timedelta
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

from data.drivers import DRIVERS
from data.winners import WINNERS

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8000))
ADMIN_IDS = [7025868617, 7946032603]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== РЕДКОСТИ =====
RARITIES = {
    "REGULAR": {"emoji": "🟢", "rating": 10, "chance": 50},
    "RARE": {"emoji": "⭐", "rating": 25, "chance": 25},
    "EXCLUSIVE": {"emoji": "🔮", "rating": 40, "chance": 15},
    "LEGENDARY": {"emoji": "💎", "rating": 60, "chance": 7},
    "INDY_EDITION": {"emoji": "🏁", "rating": 100, "chance": 2},
    "ULTIMATE": {"emoji": "👑", "rating": 150, "chance": 1},
}

# ===== БАЗА ДАННЫХ =====
def init_db():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        display_name TEXT,
        balance INTEGER DEFAULT 500,
        rating INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        game_attempts INTEGER DEFAULT 3,
        last_game_attempt TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS user_cards (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        code TEXT,
        quantity INTEGER DEFAULT 1,
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
        image TEXT,
        change_24h REAL DEFAULT 0.0
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
    c.execute("""CREATE TABLE IF NOT EXISTS promocodes (
        code TEXT PRIMARY KEY,
        reward_type TEXT,
        reward_value TEXT,
        max_uses INTEGER,
        used INTEGER DEFAULT 0,
        created_by INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS promo_usage (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        code TEXT,
        user_id INTEGER,
        used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        UNIQUE(code, user_id)
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS market_listings (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        card_code TEXT,
        price INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        status TEXT DEFAULT 'active'
    )""")
    c.execute("""CREATE TABLE IF NOT EXISTS pvp_battles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        player1_id INTEGER,
        player2_id INTEGER,
        bet_type TEXT,
        bet_value TEXT,
        status TEXT DEFAULT 'waiting',
        winner_id INTEGER,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    conn.commit()
    conn.close()

def seed_data():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    for code, data in DRIVERS.items():
        c.execute("""INSERT OR IGNORE INTO cards (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, data["name"], data["team"], data.get("number", 0), data["rarity"], data["price"],
             RARITIES.get(data["rarity"], {}).get("rating", 10), data.get("year", 2026), 
             data.get("image", "https://via.placeholder.com/150/FF0000/FFFFFF?text=No+Image")))
    for name, data in WINNERS.items():
        code = f"WIN_{name[:3].upper()}_{data['year']}"
        c.execute("""INSERT OR IGNORE INTO cards (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, name, "Indy 500 Winner", 0, data["rarity"], data["price"],
             RARITIES.get(data["rarity"], {}).get("rating", 10), data["year"], 
             "https://via.placeholder.com/150/FFD700/FFFFFF?text=Indy500"))
    conn.commit()
    conn.close()

init_db()
seed_data()

# ===== ФУНКЦИИ =====
def get_user(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT * FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row

def create_user(user_id, username):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    name = username or f"User{user_id}"
    c.execute("INSERT OR IGNORE INTO users (user_id, username, display_name) VALUES (?, ?, ?)",
              (user_id, username, name))
    conn.commit()
    conn.close()

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
    return row

def add_card_to_user(user_id, code):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("INSERT INTO user_cards (user_id, code, quantity) VALUES (?, ?, 1) "
              "ON CONFLICT(user_id, code) DO UPDATE SET quantity = quantity + 1",
              (user_id, code))
    conn.commit()
    conn.close()

def remove_card_from_user(user_id, code):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE user_cards SET quantity = quantity - 1 WHERE user_id = ? AND code = ?", (user_id, code))
    c.execute("DELETE FROM user_cards WHERE user_id = ? AND code = ? AND quantity <= 0", (user_id, code))
    conn.commit()
    conn.close()

def is_admin(user_id):
    return user_id in ADMIN_IDS

def get_rarity_emoji(rarity):
    return RARITIES.get(rarity, {}).get("emoji", "🟢")

def get_game_attempts(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT game_attempts FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 3

def use_game_attempt(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = game_attempts - 1 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def reset_game_attempts(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = 3 WHERE user_id = ?", (user_id,))
    conn.commit()
    conn.close()

def create_promo(reward_type, reward_value, max_uses, admin_id):
    code = ''.join(random.choices(string.ascii_uppercase + string.digits, k=8))
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("INSERT INTO promocodes (code, reward_type, reward_value, max_uses, created_by) VALUES (?, ?, ?, ?, ?)",
              (code, reward_type, reward_value, max_uses, admin_id))
    conn.commit()
    conn.close()
    return code

def use_promo(code, user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT 1 FROM promo_usage WHERE code = ? AND user_id = ?", (code, user_id))
    if c.fetchone():
        conn.close()
        return {"status": "error", "message": "Ты уже активировал этот промокод"}
    c.execute("SELECT reward_type, reward_value, max_uses, used FROM promocodes WHERE code = ?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"status": "error", "message": "Промокод не найден"}
    reward_type, reward_value, max_uses, used = row
    if used >= max_uses:
        conn.close()
        return {"status": "error", "message": "Промокод использован"}
    if reward_type == "coins":
        amount = int(reward_value)
        update_balance(user_id, amount, "promo")
        result = {"status": "success", "message": f"Получено {amount} 💰"}
    else:
        card_code = reward_value
        add_card_to_user(user_id, card_code)
        card = get_card_info(card_code)
        result = {"status": "success", "message": f"Получена карта {card[1]} ({card[0]})"}
    c.execute("UPDATE promocodes SET used = used + 1 WHERE code = ?", (code,))
    c.execute("INSERT INTO promo_usage (code, user_id) VALUES (?, ?)", (code, user_id))
    conn.commit()
    conn.close()
    return result

def add_market_listing(user_id, card_code, price):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("INSERT INTO market_listings (user_id, card_code, price) VALUES (?, ?, ?)",
              (user_id, card_code, price))
    conn.commit()
    conn.close()

def get_market_listings():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT id, user_id, card_code, price FROM market_listings WHERE status = 'active'")
    rows = c.fetchall()
    conn.close()
    return rows

def remove_market_listing(listing_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE market_listings SET status = 'sold' WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()

def update_card_price(code, change):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT price FROM cards WHERE code = ?", (code,))
    row = c.fetchone()
    if row:
        new_price = int(row[0] * (1 + change / 100))
        if new_price < 10:
            new_price = 10
        c.execute("UPDATE cards SET price = ?, change_24h = ? WHERE code = ?",
                 (new_price, change, code))
    conn.commit()
    conn.close()

def create_pvp_battle(player1_id, bet_type, bet_value):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("INSERT INTO pvp_battles (player1_id, bet_type, bet_value, status) VALUES (?, ?, ?, 'waiting')",
              (player1_id, bet_type, bet_value))
    battle_id = c.lastrowid
    conn.commit()
    conn.close()
    return battle_id

def get_pvp_battle(battle_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT * FROM pvp_battles WHERE id = ?", (battle_id,))
    row = c.fetchone()
    conn.close()
    return row

def join_pvp_battle(battle_id, player2_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE pvp_battles SET player2_id = ?, status = 'active' WHERE id = ?", (player2_id, battle_id))
    conn.commit()
    conn.close()

def finish_pvp_battle(battle_id, winner_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE pvp_battles SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, battle_id))
    conn.commit()
    conn.close()

def get_rating(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    # Считаем рейтинг: сумма очков редкости карт + баланс / 10
    c.execute("""
        SELECT COALESCE(SUM(c.rating_points * uc.quantity), 0) + COALESCE(u.balance / 10, 0)
        FROM users u
        LEFT JOIN user_cards uc ON u.user_id = uc.user_id
        LEFT JOIN cards c ON uc.code = c.code
        WHERE u.user_id = ?
    """, (user_id,))
    row = c.fetchone()
    conn.close()
    return row[0] if row else 0

def update_user_rating(user_id):
    rating = get_rating(user_id)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET rating = ? WHERE user_id = ?", (rating, user_id))
    conn.commit()
    conn.close()

def get_top_players(limit=10):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT display_name, rating, balance FROM users ORDER BY rating DESC LIMIT ?", (limit,))
    rows = c.fetchall()
    conn.close()
    return rows

# ===== СЕССИИ =====
user_card_pages = {}
user_market_session = {}
admin_price_session = {}
user_sell_session = {}
pvp_sessions = {}

# ===== КЛАВИАТУРЫ =====
def main_menu(user_id=None):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
         InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card")],
        [InlineKeyboardButton(text="🏦 Биржа", callback_data="exchange"),
         InlineKeyboardButton(text="📊 Рынок", callback_data="player_market")],
        [InlineKeyboardButton(text="⚔️ PvP Кубики", callback_data="pvp_menu")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🏪 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🎁 Промокод", callback_data="promo_enter"),
         InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about")]
    ])
    if user_id and is_admin(user_id):
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="👑 Админ-панель", callback_data="admin_panel")
        ])
    return markup

def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def shop_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Попытка в игру (50 💰)", callback_data="shop_attempt")],
        [InlineKeyboardButton(text="🎴 Случайная карта (100 💰)", callback_data="shop_card")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🎁 Создать промокод", callback_data="admin_promo")],
        [InlineKeyboardButton(text="💰 Управление ценами", callback_data="admin_price")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def admin_promo_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Карта", callback_data="admin_promo_card")],
        [InlineKeyboardButton(text="💰 Монеты", callback_data="admin_promo_coins")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def pvp_bet_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Деньги", callback_data="pvp_bet_money")],
        [InlineKeyboardButton(text="🎴 Карта", callback_data="pvp_bet_card")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def pvp_money_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 💰", callback_data="pvp_money_10")],
        [InlineKeyboardButton(text="25 💰", callback_data="pvp_money_25")],
        [InlineKeyboardButton(text="50 💰", callback_data="pvp_money_50")],
        [InlineKeyboardButton(text="100 💰", callback_data="pvp_money_100")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="pvp_menu")]
    ])

# ===== БОТ =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== СТАРТ =====
@dp.message(Command("start"))
async def start_command(message: Message):
    create_user(message.from_user.id, message.from_user.username)
    update_user_rating(message.from_user.id)
    await message.answer(
        "🏁 **IndyCard Exchange**\n\n"
        "💰 Баланс: 500 💰\n"
        "🎲 Попыток: 3/3ч\n\n"
        "Выбирай действие:",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

# ===== МЯГКАЯ ОБРАБОТКА =====
@dp.message()
async def handle_messages(message: Message):
    text = message.text.strip()
    if len(text) == 8 and text.isalnum():
        result = use_promo(text.upper(), message.from_user.id)
        await message.answer(f"🎁 **Результат**\n\n{result['message']}", parse_mode="Markdown")
        return

# ===== КНОПКИ =====
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(call: CallbackQuery):
    await call.message.edit_text(
        "🏁 **Главное меню**",
        reply_markup=main_menu(call.from_user.id),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "about")
async def about(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ **IndyCard Exchange**\n\n"
        "Карточная игра по мотивам IndyCar.\n\n"
        "🎴 Собирай карты пилотов и легенд\n"
        "🏦 Торгуй на бирже и рынке игроков\n"
        "⚔️ Играй в PvP на кубиках\n"
        "🎲 Проходи мини-игры\n\n"
        "Разработчики:\n"
        "@Scanialove\n"
        "@Gabriella1488\n\n"
        "❤️ Поддержать проект:\n"
        "https://www.donationalerts.com/r/kimi_redrace",
        reply_markup=back_menu(),
        parse_mode="Markdown",
        disable_web_page_preview=True
    )
    await call.answer()

@dp.callback_query(F.data == "promo_enter")
async def promo_enter(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 **Введите промокод**\n\n"
        "Отправь код в сообщении (8 символов)",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "my_cards")
async def my_cards(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    if not cards:
        await call.message.edit_text("📭 Нет карт", reply_markup=back_menu())
        await call.answer()
        return
    
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, "EXCLUSIVE": 3, "RARE": 4, "REGULAR": 5}
    sorted_cards = sorted(cards.items(), key=lambda x: rarity_order.get(get_card_info(x[0])[4], 99))
    
    page = user_card_pages.get(user_id, 0)
    total_pages = (len(sorted_cards) + 4) // 5
    if page >= total_pages:
        page = total_pages - 1
        user_card_pages[user_id] = page
    start = page * 5
    end = start + 5
    page_cards = sorted_cards[start:end]
    
    text = "🎴 **Мои карты**\n\n"
    for code, qty in page_cards:
        card = get_card_info(code)
        if card:
            emoji = get_rarity_emoji(card[4])
            text += f"{emoji} {card[1]} ({code}) ×{qty}\n"
    text += f"\n📊 Всего: {sum(cards.values())} карт"
    if total_pages > 1:
        text += f"\n📄 Страница {page+1} из {total_pages}"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️", callback_data="cards_prev"),
            InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="cards_page"),
            InlineKeyboardButton(text="▶️", callback_data="cards_next")
        ],
        [
            InlineKeyboardButton(text="💸 Продать", callback_data="sell_menu"),
            InlineKeyboardButton(text="📊 На рынок", callback_data="market_sell")
        ],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "cards_next")
async def cards_next(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    total_pages = (len(cards) + 4) // 5
    user_card_pages[user_id] = min(user_card_pages.get(user_id, 0) + 1, total_pages - 1)
    await my_cards(call)

@dp.callback_query(F.data == "cards_prev")
async def cards_prev(call: CallbackQuery):
    user_id = call.from_user.id
    user_card_pages[user_id] = max(0, user_card_pages.get(user_id, 0) - 1)
    await my_cards(call)

@dp.callback_query(F.data == "get_card")
async def get_card(call: CallbackQuery):
    rarities = [r for r, d in RARITIES.items() for _ in range(d["chance"])]
    rarity = random.choice(rarities)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,))
    row = c.fetchone()
    conn.close()
    if not row:
        await call.answer("❌ Нет карт", show_alert=True)
        return
    code = row[0]
    add_card_to_user(call.from_user.id, code)
    update_user_rating(call.from_user.id)
    card = get_card_info(code)
    await call.message.edit_text(
        f"🎲 **Получена карта!**\n\n"
        f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {card[4]}\n"
        f"💰 {card[5]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "exchange")
async def exchange(call: CallbackQuery):
    user = get_user(call.from_user.id)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, rarity, price, change_24h FROM cards ORDER BY price DESC LIMIT 15")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await call.message.edit_text("📭 Нет карт", reply_markup=back_menu())
        await call.answer()
        return
    
    text = "🏦 **Биржа**\n\n💰 Баланс: {}\n\n".format(user[2])
    for code, name, rarity, price, change in rows:
        emoji = get_rarity_emoji(rarity)
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        text += f"{emoji} {name} ({code}) — {price} 💰 {arrow} {change:.1f}%\n"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить цены", callback_data="exchange_refresh")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    # Добавляем кнопки покупки для каждой карты
    for code, name, rarity, price, change in rows[:5]:
        markup.inline_keyboard.insert(0, [
            InlineKeyboardButton(text=f"💎 {name} ({code}) — {price} 💰", callback_data=f"buy_{code}")
        ])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "exchange_refresh")
async def exchange_refresh(call: CallbackQuery):
    # Обновляем цены рандомно
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code FROM cards")
    rows = c.fetchall()
    for row in rows:
        change = random.uniform(-5, 5)
        update_card_price(row[0], change)
    conn.close()
    await call.answer("🔄 Цены обновлены!")
    await exchange(call)

@dp.callback_query(F.data.startswith("buy_"))
async def buy_card_from_exchange(call: CallbackQuery):
    code = call.data.replace("buy_", "")
    user_id = call.from_user.id
    
    card = get_card_info(code)
    if not card:
        await call.answer("❌ Карта не найдена")
        return
    
    user = get_user(user_id)
    if user[2] < card[5]:
        await call.answer(f"❌ Нужно {card[5]} 💰", show_alert=True)
        return
    
    update_balance(user_id, -card[5], "buy", code)
    add_card_to_user(user_id, code)
    update_user_rating(user_id)
    
    await call.message.edit_text(
        f"✅ {card[1]} ({code}) куплена за {card[5]} 💰\n"
        f"💰 Новый баланс: {user[2] - card[5]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "player_market")
async def player_market(call: CallbackQuery):
    listings = get_market_listings()
    if not listings:
        await call.message.edit_text(
            "📊 **Рынок игроков**\n\nНа рынке пока нет карт.\n"
            "Ты можешь выставить свою карту через 'Мои карты'.",
            reply_markup=back_menu(),
            parse_mode="Markdown"
        )
        await call.answer()
        return
    
    text = "📊 **Рынок игроков**\n\n"
    for listing_id, user_id, card_code, price in listings:
        card = get_card_info(card_code)
        if not card:
            continue
        seller = get_user(user_id)
        seller_name = seller[1] or seller[3] or "Неизвестно"
        emoji = get_rarity_emoji(card[4])
        text += f"{emoji} {card[1]} ({card[0]}) — {price} 💰 (от @{seller_name})\n"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for listing_id, user_id, card_code, price in listings:
        card = get_card_info(card_code)
        if not card:
            continue
        markup.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"💎 Купить {card[1]} ({card[0]}) за {price} 💰",
                callback_data=f"market_buy_{listing_id}"
            )
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("market_buy_"))
async def market_buy(call: CallbackQuery):
    listing_id = int(call.data.replace("market_buy_", ""))
    buyer_id = call.from_user.id
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT user_id, card_code, price FROM market_listings WHERE id = ? AND status = 'active'", (listing_id,))
    row = c.fetchone()
    conn.close()
    
    if not row:
        await call.answer("❌ Карта уже продана", show_alert=True)
        return
    
    seller_id, card_code, price = row
    
    if buyer_id == seller_id:
        await call.answer("❌ Нельзя купить свою карту", show_alert=True)
        return
    
    buyer = get_user(buyer_id)
    if buyer[2] < price:
        await call.answer(f"❌ Нужно {price} 💰", show_alert=True)
        return
    
    seller_cards = get_user_cards(seller_id)
    if seller_cards.get(card_code, 0) < 1:
        await call.answer("❌ У продавца больше нет этой карты", show_alert=True)
        return
    
    update_balance(buyer_id, -price, "market_buy", card_code)
    update_balance(seller_id, price, "market_sell", card_code)
    remove_card_from_user(seller_id, card_code)
    add_card_to_user(buyer_id, card_code)
    remove_market_listing(listing_id)
    update_user_rating(buyer_id)
    update_user_rating(seller_id)
    
    await call.message.edit_text(
        f"✅ Покупка совершена!\n\n"
        f"Карта {card_code} куплена за {price} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "sell_menu")
async def sell_menu(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    if not cards:
        await call.message.edit_text("📭 Нет карт для продажи", reply_markup=back_menu())
        await call.answer()
        return
    
    card_list = list(cards.keys())
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, "EXCLUSIVE": 3, "RARE": 4, "REGULAR": 5}
    card_list.sort(key=lambda x: rarity_order.get(get_card_info(x)[4], 99))
    
    user_sell_session[user_id] = {"cards": card_list, "index": 0}
    await show_sell_card(call.message, user_id)
    await call.answer()

async def show_sell_card(message, user_id):
    session = user_sell_session.get(user_id)
    if not session:
        return
    
    index = session["index"]
    cards = session["cards"]
    if index >= len(cards):
        index = 0
        session["index"] = 0
    
    code = cards[index]
    card = get_card_info(code)
    if not card:
        return
    
    qty = get_user_cards(user_id).get(code, 0)
    price = int(card[5] * 0.7)
    total = len(cards)
    emoji = get_rarity_emoji(card[4])
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️", callback_data="sell_prev"),
            InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="sell_count"),
            InlineKeyboardButton(text="▶️", callback_data="sell_next")
        ],
        [
            InlineKeyboardButton(text=f"💰 Продать за {price} 💰", callback_data=f"sell_confirm_{code}")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
        ]
    ])
    
    await message.edit_text(
        f"💵 **Продажа карты**\n\n"
        f"{emoji} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {card[4]}\n"
        f"💰 Цена: {card[5]} 💰\n"
        f"💸 Продажа за: {price} 💰\n"
        f"📦 Количество: {qty}\n\n"
        f"Карта {index+1} из {total}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "sell_next")
async def sell_next(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_sell_session:
        await call.answer("❌ Сессия истекла")
        return
    user_sell_session[user_id]["index"] += 1
    await show_sell_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data == "sell_prev")
async def sell_prev(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_sell_session:
        await call.answer("❌ Сессия истекла")
        return
    user_sell_session[user_id]["index"] -= 1
    if user_sell_session[user_id]["index"] < 0:
        user_sell_session[user_id]["index"] = 0
    await show_sell_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data.startswith("sell_confirm_"))
async def sell_confirm(call: CallbackQuery):
    code = call.data.replace("sell_confirm_", "")
    user_id = call.from_user.id
    
    card = get_card_info(code)
    if not card:
        await call.answer("❌ Карта не найдена")
        return
    
    cards = get_user_cards(user_id)
    if cards.get(code, 0) < 1:
        await call.answer("❌ У тебя нет этой карты")
        return
    
    price = int(card[5] * 0.7)
    remove_card_from_user(user_id, code)
    update_balance(user_id, price, "sell", code)
    update_user_rating(user_id)
    
    remaining = get_user_cards(user_id)
    if not remaining:
        await call.message.edit_text(
            f"✅ {card[1]} ({code}) продана за {price} 💰\n"
            f"💰 Новый баланс: {get_user(user_id)[2]} 💰\n\n"
            "📭 У тебя больше нет карт",
            reply_markup=back_menu(),
            parse_mode="Markdown"
        )
        await call.answer()
        return
    
    if user_id in user_sell_session:
        user_sell_session[user_id]["cards"] = list(remaining.keys())
        if user_sell_session[user_id]["index"] >= len(user_sell_session[user_id]["cards"]):
            user_sell_session[user_id]["index"] = 0
        await show_sell_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data == "market_sell")
async def market_sell_start(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    if not cards:
        await call.message.edit_text("📭 Нет карт для выставления", reply_markup=back_menu())
        await call.answer()
        return
    
    card_list = list(cards.keys())
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, "EXCLUSIVE": 3, "RARE": 4, "REGULAR": 5}
    card_list.sort(key=lambda x: rarity_order.get(get_card_info(x)[4], 99))
    
    user_market_session[user_id] = {"cards": card_list, "index": 0, "price": 0}
    await show_market_card(call.message, user_id)
    await call.answer()

async def show_market_card(message, user_id):
    session = user_market_session.get(user_id)
    if not session:
        return
    
    index = session["index"]
    cards = session["cards"]
    if index >= len(cards):
        index = 0
        session["index"] = 0
    
    code = cards[index]
    card = get_card_info(code)
    if not card:
        return
    
    qty = get_user_cards(user_id).get(code, 0)
    price = session.get("price", card[5])
    total = len(cards)
    emoji = get_rarity_emoji(card[4])
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="◀️", callback_data="market_prev"),
            InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="market_count"),
            InlineKeyboardButton(text="▶️", callback_data="market_next")
        ],
        [
            InlineKeyboardButton(text="🔽 -10", callback_data="market_price_-10"),
            InlineKeyboardButton(text=f"{price} 💰", callback_data="market_price_show"),
            InlineKeyboardButton(text="🔼 +10", callback_data="market_price_+10")
        ],
        [
            InlineKeyboardButton(text=f"📊 Выставить за {price} 💰", callback_data=f"market_list_{code}")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")
        ]
    ])
    
    await message.edit_text(
        f"📊 **Выставление на рынок**\n\n"
        f"{emoji} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {card[4]}\n"
        f"💰 Базовая цена: {card[5]} 💰\n"
        f"📦 Количество: {qty}\n\n"
        f"Установи цену кнопками и нажми 'Выставить'",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data.startswith("market_price_"))
async def market_price_change(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_market_session:
        await call.answer("❌ Сессия истекла")
        return
    
    change = int(call.data.replace("market_price_", ""))
    session = user_market_session[user_id]
    card = get_card_info(session["cards"][session["index"]])
    if not card:
        return
    
    new_price = session.get("price", card[5]) + change
    if new_price < 10:
        new_price = 10
    session["price"] = new_price
    
    await show_market_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data.startswith("market_list_"))
async def market_list(call: CallbackQuery):
    user_id = call.from_user.id
    code = call.data.replace("market_list_", "")
    
    if user_id not in user_market_session:
        await call.answer("❌ Сессия истекла")
        return
    
    session = user_market_session[user_id]
    price = session.get("price", 0)
    
    if price < 10:
        await call.answer("❌ Цена должна быть не меньше 10 💰", show_alert=True)
        return
    
    card = get_card_info(code)
    if not card:
        await call.answer("❌ Карта не найдена")
        return
    
    cards = get_user_cards(user_id)
    if cards.get(code, 0) < 1:
        await call.answer("❌ У тебя нет этой карты")
        return
    
    add_market_listing(user_id, code, price)
    remove_card_from_user(user_id, code)
    update_user_rating(user_id)
    
    await call.message.edit_text(
        f"✅ Карта {card[1]} ({code}) выставлена на рынок за {price} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "market_next")
async def market_next(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_market_session:
        await call.answer("❌ Сессия истекла")
        return
    user_market_session[user_id]["index"] += 1
    await show_market_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data == "market_prev")
async def market_prev(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_market_session:
        await call.answer("❌ Сессия истекла")
        return
    user_market_session[user_id]["index"] -= 1
    if user_market_session[user_id]["index"] < 0:
        user_market_session[user_id]["index"] = 0
    await show_market_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data == "shop")
async def shop(call: CallbackQuery):
    await call.message.edit_text(
        "🏪 **Магазин**\n\n"
        "🎲 Попытка в игру — 50 💰\n"
        "🎴 Случайная карта — 100 💰",
        reply_markup=shop_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "shop_attempt")
async def shop_attempt(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user[2] < 50:
        await call.answer("❌ Нужно 50 💰", show_alert=True)
        return
    update_balance(call.from_user.id, -50, "shop")
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = game_attempts + 1 WHERE user_id = ?", (call.from_user.id,))
    conn.commit()
    conn.close()
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"✅ Попытка куплена!\n"
        f"🎲 Попыток: {user[6]}\n"
        f"💰 Баланс: {user[2]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "shop_card")
async def shop_card(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user[2] < 100:
        await call.answer("❌ Нужно 100 💰", show_alert=True)
        return
    update_balance(call.from_user.id, -100, "shop")
    rarities = [r for r, d in RARITIES.items() for _ in range(d["chance"])]
    rarity = random.choice(rarities)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,))
    row = c.fetchone()
    conn.close()
    if row:
        code = row[0]
        add_card_to_user(call.from_user.id, code)
        update_user_rating(call.from_user.id)
        card = get_card_info(code)
        await call.message.edit_text(
            f"🎴 Куплена карта!\n\n{get_rarity_emoji(card[4])} {card[1]} ({card[0]})",
            reply_markup=back_menu(),
            parse_mode="Markdown"
        )
    else:
        await call.message.edit_text("❌ Нет карт", reply_markup=back_menu())
    await call.answer()

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    user = get_user(call.from_user.id)
    cards = get_user_cards(call.from_user.id)
    total = sum(cards.values())
    attempts = get_game_attempts(call.from_user.id)
    rating = user[4] if user else 0
    await call.message.edit_text(
        f"👤 **Профиль**\n\n"
        f"Имя: {user[1] or user[3]}\n"
        f"💰 Баланс: {user[2]} 💰\n"
        f"🎴 Карт: {total}\n"
        f"🏆 Рейтинг: {rating}\n"
        f"🎲 Попыток: {attempts}",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== PVP =====
@dp.callback_query(F.data == "pvp_menu")
async def pvp_menu(call: CallbackQuery):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Создать битву", callback_data="pvp_create")],
        [InlineKeyboardButton(text="📋 Список битв", callback_data="pvp_list")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await call.message.edit_text(
        "⚔️ **PvP Кубики**\n\n"
        "Создай битву или присоединись к существующей.\n"
        "Ставка: деньги или карта.\n"
        "У кого больше выпало на кубиках — тот и выиграл!",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "pvp_create")
async def pvp_create(call: CallbackQuery):
    await call.message.edit_text(
        "⚔️ **Создание битвы**\n\n"
        "Что ставишь?",
        reply_markup=pvp_bet_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "pvp_bet_money")
async def pvp_bet_money(call: CallbackQuery):
    await call.message.edit_text(
        "💰 **Ставка деньгами**\n\n"
        "Выбери сумму:",
        reply_markup=pvp_money_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("pvp_money_"))
async def pvp_money_create(call: CallbackQuery):
    user_id = call.from_user.id
    amount = int(call.data.replace("pvp_money_", ""))
    
    user = get_user(user_id)
    if user[2] < amount:
        await call.answer(f"❌ Нужно {amount} 💰", show_alert=True)
        return
    
    battle_id = create_pvp_battle(user_id, "money", str(amount))
    await call.message.edit_text(
        f"⚔️ **Битва создана!**\n\n"
        f"ID: {battle_id}\n"
        f"Ставка: {amount} 💰\n\n"
        f"Ожидаем соперника...\n"
        f"Дай этот ID другу: `{battle_id}`",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "pvp_bet_card")
async def pvp_bet_card(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    if not cards:
        await call.message.edit_text("📭 Нет карт для ставки", reply_markup=back_menu())
        await call.answer()
        return
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for code, qty in cards.items():
        card = get_card_info(code)
        if card:
            markup.inline_keyboard.append([
                InlineKeyboardButton(
                    text=f"{get_rarity_emoji(card[4])} {card[1]} ({code}) ×{qty}",
                    callback_data=f"pvp_card_{code}"
                )
            ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="pvp_menu")])
    
    await call.message.edit_text(
        "🎴 **Выбери карту для ставки**",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("pvp_card_"))
async def pvp_card_create(call: CallbackQuery):
    user_id = call.from_user.id
    code = call.data.replace("pvp_card_", "")
    
    cards = get_user_cards(user_id)
    if cards.get(code, 0) < 1:
        await call.answer("❌ У тебя нет этой карты", show_alert=True)
        return
    
    battle_id = create_pvp_battle(user_id, "card", code)
    await call.message.edit_text(
        f"⚔️ **Битва создана!**\n\n"
        f"ID: {battle_id}\n"
        f"Ставка: карта {get_card_info(code)[1]}\n\n"
        f"Ожидаем соперника...\n"
        f"Дай этот ID другу: `{battle_id}`",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "pvp_list")
async def pvp_list(call: CallbackQuery):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT id, player1_id, bet_type, bet_value FROM pvp_battles WHERE status = 'waiting'")
    rows = c.fetchall()
    conn.close()
    
    if not rows:
        await call.message.edit_text("📭 Нет активных битв", reply_markup=back_menu())
        await call.answer()
        return
    
    text = "⚔️ **Активные битвы**\n\n"
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for battle_id, player1_id, bet_type, bet_value in rows:
        player = get_user(player1_id)
        player_name = player[1] or player[3] or "Неизвестно"
        bet_text = f"{bet_value} 💰" if bet_type == "money" else f"карта {bet_value}"
        text += f"ID {battle_id}: @{player_name} ставит {bet_text}\n"
        markup.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"⚔️ Присоединиться к {battle_id}",
                callback_data=f"pvp_join_{battle_id}"
            )
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="pvp_menu")])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("pvp_join_"))
async def pvp_join(call: CallbackQuery):
    battle_id = int(call.data.replace("pvp_join_", ""))
    player2_id = call.from_user.id
    
    battle = get_pvp_battle(battle_id)
    if not battle or battle[4] != "waiting":
        await call.answer("❌ Битва уже завершена", show_alert=True)
        return
    
    if battle[1] == player2_id:
        await call.answer("❌ Нельзя присоединиться к своей битве", show_alert=True)
        return
    
    join_pvp_battle(battle_id, player2_id)
    
    # Бросаем кубики
    d1_p1, d2_p1 = random.randint(1, 6), random.randint(1, 6)
    d1_p2, d2_p2 = random.randint(1, 6), random.randint(1, 6)
    total_p1 = d1_p1 + d2_p1
    total_p2 = d1_p2 + d2_p2
    
    winner_id = battle[1] if total_p1 > total_p2 else player2_id if total_p2 > total_p1 else None
    
    finish_pvp_battle(battle_id, winner_id)
    
    # Передаём ставку
    if winner_id:
        bet_type = battle[3]
        bet_value = battle[4]
        if bet_type == "money":
            amount = int(bet_value)
            update_balance(winner_id, amount, "pvp_win")
            update_balance(battle[1] if winner_id == player2_id else player2_id, -amount, "pvp_loss")
        else:
            # Карта переходит победителю
            loser_id = battle[1] if winner_id == player2_id else player2_id
            remove_card_from_user(loser_id, bet_value)
            add_card_to_user(winner_id, bet_value)
    
    # Обновляем рейтинг
    update_user_rating(battle[1])
    update_user_rating(player2_id)
    if winner_id:
        update_user_rating(winner_id)
    
    await call.message.edit_text(
        f"⚔️ **Результат битвы {battle_id}**\n\n"
        f"Игрок 1: {d1_p1} + {d2_p1} = {total_p1}\n"
        f"Игрок 2: {d1_p2} + {d2_p2} = {total_p2}\n\n"
        f"{'🏆 Победил Игрок 1!' if winner_id == battle[1] else '🏆 Победил Игрок 2!' if winner_id else '🤝 Ничья!'}",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== АДМИН =====
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await call.message.edit_text("👑 **Админ-панель**", reply_markup=admin_menu(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_list")
async def admin_list(call: CallbackQuery):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, rarity, price FROM cards")
    rows = c.fetchall()
    conn.close()
    text = "📋 **Карты**\n\n"
    for code, name, rarity, price in rows:
        text += f"{get_rarity_emoji(rarity)} {name} ({code}) — {rarity} — {price} 💰\n"
    await call.message.edit_text(text[:4000], reply_markup=back_menu(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    c.execute("SELECT COUNT(*) FROM cards")
    cards = c.fetchone()[0]
    c.execute("SELECT SUM(quantity) FROM user_cards")
    total = c.fetchone()[0] or 0
    conn.close()
    await call.message.edit_text(
        f"📊 **Статистика**\n\n👥 Пользователей: {users}\n🎴 Карт: {cards}\n📦 У игроков: {total}",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_promo")
async def admin_promo_start(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    await call.message.edit_text(
        "🎁 **Создание промокода**\n\nЧто будет наградой?",
        reply_markup=admin_promo_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_promo_card")
async def admin_promo_card(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, rarity FROM cards ORDER BY price DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"{get_rarity_emoji(row[2])} {row[1]} ({row[0]})", 
                              callback_data=f"promo_card_{row[0]}")]
        for row in rows
    ] + [[InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promo")]])
    await call.message.edit_text(
        "🎁 **Выбери карту для промокода**",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_promo_coins")
async def admin_promo_coins(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    await call.message.edit_text(
        "💵 **Введите сумму монет**\n\n"
        "Отправь число в сообщении",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message()
async def handle_admin_promo_coins(message: Message):
    if not is_admin(message.from_user.id):
        return
    try:
        amount = int(message.text.strip())
        code = create_promo("coins", str(amount), 10, message.from_user.id)
        await message.answer(
            f"🎁 **Промокод создан!**\n\n"
            f"Код: `{code}`\n"
            f"Награда: {amount} 💰\n"
            f"Активаций: 10",
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Введи число")

@dp.callback_query(F.data.startswith("promo_card_"))
async def promo_card_create(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        return
    card_code = call.data.replace("promo_card_", "")
    code = create_promo("card", card_code, 5, call.from_user.id)
    card = get_card_info(card_code)
    await call.message.edit_text(
        f"🎁 **Промокод создан!**\n\n"
        f"Код: `{code}`\n"
        f"Награда: {card[1]} ({card[0]})\n"
        f"Активаций: 5",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_price")
async def admin_price_menu(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, rarity, price FROM cards ORDER BY price DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for code, name, rarity, price in rows:
        emoji = get_rarity_emoji(rarity)
        markup.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{emoji} {name} ({code}) — {price} 💰",
                callback_data=f"price_edit_{code}"
            )
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    await call.message.edit_text(
        "💰 **Управление ценами**\n\nВыбери карту для изменения цены:",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("price_edit_"))
async def price_edit(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    
    code = call.data.replace("price_edit_", "")
    card = get_card_info(code)
    if not card:
        await call.answer("❌ Карта не найдена")
        return
    
    admin_price_session[call.from_user.id] = code
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔽 -10", callback_data=f"price_change_-10"),
            InlineKeyboardButton(text="🔼 +10", callback_data=f"price_change_+10")
        ],
        [
            InlineKeyboardButton(text="🔽 -50", callback_data=f"price_change_-50"),
            InlineKeyboardButton(text="🔼 +50", callback_data=f"price_change_+50")
        ],
        [
            InlineKeyboardButton(text="🔽 -100", callback_data=f"price_change_-100"),
            InlineKeyboardButton(text="🔼 +100", callback_data=f"price_change_+100")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="admin_price")
        ]
    ])
    
    await call.message.edit_text(
        f"💰 **Изменение цены**\n\n"
        f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n"
        f"Текущая цена: {card[5]} 💰\n\n"
        f"Выбери изменение:",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("price_change_"))
async def price_change(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Нет доступа", show_alert=True)
        return
    
    change = int(call.data.replace("price_change_", ""))
    code = admin_price_session.get(call.from_user.id)
    if not code:
        await call.answer("❌ Сессия истекла")
        return
    
    card = get_card_info(code)
    if not card:
        await call.answer("❌ Карта не найдена")
        return
    
    new_price = card[5] + change
    if new_price < 10:
        new_price = 10
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE cards SET price = ? WHERE code = ?", (new_price, code))
    conn.commit()
    conn.close()
    
    await call.answer(f"✅ Цена изменена: {card[5]} → {new_price} 💰")
    
    card = get_card_info(code)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="🔽 -10", callback_data=f"price_change_-10"),
            InlineKeyboardButton(text="🔼 +10", callback_data=f"price_change_+10")
        ],
        [
            InlineKeyboardButton(text="🔽 -50", callback_data=f"price_change_-50"),
            InlineKeyboardButton(text="🔼 +50", callback_data=f"price_change_+50")
        ],
        [
            InlineKeyboardButton(text="🔽 -100", callback_data=f"price_change_-100"),
            InlineKeyboardButton(text="🔼 +100", callback_data=f"price_change_+100")
        ],
        [
            InlineKeyboardButton(text="🔙 Назад", callback_data="admin_price")
        ]
    ])
    
    await call.message.edit_text(
        f"💰 **Изменение цены**\n\n"
        f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n"
        f"Текущая цена: {card[5]} 💰\n\n"
        f"Выбери изменение:",
        reply_markup=markup,
        parse_mode="Markdown"
    )

# ===== МИНИ-ИГРЫ =====
@dp.callback_query(F.data == "game_guess")
async def game_guess(call: CallbackQuery):
    attempts = get_game_attempts(call.from_user.id)
    if attempts <= 0:
        await call.answer("❌ Нет попыток! Купи в магазине.", show_alert=True)
        return
    use_game_attempt(call.from_user.id)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, team FROM cards ORDER BY RANDOM() LIMIT 1")
    card = c.fetchone()
    conn.close()
    if not card:
        await call.answer("❌ Нет карт", show_alert=True)
        return
    code, name, team = card
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT name FROM cards WHERE name != ? ORDER BY RANDOM() LIMIT 3", (name,))
    others = c.fetchall()
    conn.close()
    options = [name] + [o[0] for o in others]
    random.shuffle(options)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=options[0], callback_data=f"guess_{name}_{options[0]}"),
         InlineKeyboardButton(text=options[1], callback_data=f"guess_{name}_{options[1]}")],
        [InlineKeyboardButton(text=options[2], callback_data=f"guess_{name}_{options[2]}"),
         InlineKeyboardButton(text=options[3], callback_data=f"guess_{name}_{options[3]}")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]
    ])
    await call.message.edit_text(
        f"🎲 **Угадай пилота**\n\nПодсказка: {team}\n\nКто это?",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("guess_"))
async def guess_result(call: CallbackQuery):
    parts = call.data.split("_")
    correct, answer = parts[1], parts[2]
    if correct == answer:
        win = 50
        update_balance(call.from_user.id, win, "game")
        update_user_rating(call.from_user.id)
        result = f"✅ +{win} 💰"
    else:
        result = f"❌ Это был {correct}"
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"🎲 **Результат**\n\n{result}\n\n💰 Баланс: {user[2]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "game_dice")
async def game_dice(call: CallbackQuery):
    attempts = get_game_attempts(call.from_user.id)
    if attempts <= 0:
        await call.answer("❌ Нет попыток!", show_alert=True)
        return
    use_game_attempt(call.from_user.id)
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 💰", callback_data="dice_10"),
         InlineKeyboardButton(text="25 💰", callback_data="dice_25")],
        [InlineKeyboardButton(text="50 💰", callback_data="dice_50"),
         InlineKeyboardButton(text="100 💰", callback_data="dice_100")],
        [InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu")]
    ])
    await call.message.edit_text(
        "🎲 **Бросок кубиков**\n\nВыбери ставку (х2 при 6+, х3 при 11+):",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("dice_"))
async def dice_result(call: CallbackQuery):
    bet = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    if user[2] < bet:
        await call.answer("❌ Недостаточно!", show_alert=True)
        return
    d1, d2 = random.randint(1, 6), random.randint(1, 6)
    total = d1 + d2
    if total >= 11:
        win = bet * 3
    elif total >= 6:
        win = bet * 2
    else:
        win = -bet
    update_balance(call.from_user.id, win, "game")
    update_user_rating(call.from_user.id)
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"🎲 **Результат**\n\n{d1} + {d2} = {total}\n"
        f"{'🎉 Выигрыш: ' + str(win) if win > 0 else '❌ Проигрыш: ' + str(-win)}\n"
        f"💰 Баланс: {user[2]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== ФОН =====
async def update_prices():
    while True:
        await asyncio.sleep(30)  # каждые 30 секунд для демо
        try:
            conn = sqlite3.connect("indycard.db")
            c = conn.cursor()
            c.execute("SELECT code FROM cards")
            rows = c.fetchall()
            for row in rows:
                change = random.uniform(-3, 3)
                update_card_price(row[0], change)
            conn.close()
            logger.info("✅ Цены обновлены")
        except Exception as e:
            logger.error(f"Price update error: {e}")

async def reset_attempts_task():
    while True:
        await asyncio.sleep(10800)  # 3 часа
        try:
            conn = sqlite3.connect("indycard.db")
            c = conn.cursor()
            c.execute("UPDATE users SET game_attempts = 3")
            conn.commit()
            conn.close()
            logger.info("✅ Попытки сброшены до 3")
        except Exception as e:
            logger.error(f"Reset attempts error: {e}")

# ===== ВЕБХУК =====
async def on_startup(app: web.Application):
    asyncio.create_task(update_prices())
    asyncio.create_task(reset_attempts_task())
    await bot.set_webhook(
        url=f"{WEBHOOK_URL}{WEBHOOK_PATH}",
        allowed_updates=["message", "callback_query"]
    )
    logger.info(f"✅ Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")

def main():
    app = web.Application()
    app["bot"] = bot
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
