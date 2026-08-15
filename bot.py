import os
import logging
import sqlite3
import random
import asyncio
import aiohttp
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

# ===== КОНФИГ БИРЖИ =====
EXCHANGE_SIZE = 10
ANCHOR_COUNT = 3
ROTATION_INTERVAL = 600  # 10 минут

# ===== ХРАНИЛИЩА =====
user_exchange = {}  # {user_id: {"page": 0, "filter": None}}
user_sell = {}      # {user_id: {"index": 0, "cards": []}}
exchange_cache = {
    "anchors": [],
    "rotating": [],
    "last_update": None
}

# ===== КЛАВИАТУРЫ =====
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
         InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card")],
        [InlineKeyboardButton(text="🏦 Биржа", callback_data="exchange"),
         InlineKeyboardButton(text="🎮 Мини-игры", callback_data="games")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🏪 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about")]
    ])

def back_to_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def games_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Угадай пилота", callback_data="game_guess_driver")],
        [InlineKeyboardButton(text="🗺️ Угадай трассу", callback_data="game_guess_track")],
        [InlineKeyboardButton(text="🎲 Бросок кубиков", callback_data="game_dice")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def admin_panel():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="➕ Добавить", callback_data="admin_add"),
         InlineKeyboardButton(text="📝 Редактировать", callback_data="admin_edit")],
        [InlineKeyboardButton(text="🗑️ Удалить", callback_data="admin_delete"),
         InlineKeyboardButton(text="📋 Список", callback_data="admin_list")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
         InlineKeyboardButton(text="🎁 Промокод", callback_data="admin_promo")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def shop_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Попытка в игру (50 💰)", callback_data="shop_attempt")],
        [InlineKeyboardButton(text="🎴 Случайная карта (100 💰)", callback_data="shop_card")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

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
        pvp_wins INTEGER DEFAULT 0,
        pvp_losses INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        last_game_attempt TIMESTAMP,
        game_attempts INTEGER DEFAULT 3
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
    conn.commit()
    conn.close()

def seed_data():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    for code, data in DRIVERS.items():
        c.execute("""INSERT OR IGNORE INTO cards (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, data["name"], data["team"], data.get("number", 0), data["rarity"], data["price"],
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

# ===== БАЗОВЫЕ ФУНКЦИИ =====
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
    display_name = username or f"User{user_id}"
    c.execute("INSERT OR IGNORE INTO users (user_id, username, display_name) VALUES (?, ?, ?)",
              (user_id, username, display_name))
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

def get_rarity_rating(rarity):
    return RARITIES.get(rarity, {}).get("rating", 10)

def get_game_attempts(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT game_attempts, last_game_attempt FROM users WHERE user_id = ?", (user_id,))
    row = c.fetchone()
    conn.close()
    if not row:
        return 3
    attempts, last_attempt = row
    if last_attempt:
        try:
            last_time = datetime.fromisoformat(last_attempt)
            if datetime.now() - last_time > timedelta(hours=3):
                reset_game_attempts(user_id)
                return 3
        except:
            pass
    return attempts

def use_game_attempt(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    now = datetime.now().isoformat()
    c.execute("UPDATE users SET game_attempts = game_attempts - 1, last_game_attempt = ? WHERE user_id = ?",
              (now, user_id))
    conn.commit()
    conn.close()

def reset_game_attempts(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = 3, last_game_attempt = ? WHERE user_id = ?",
              (datetime.now().isoformat(), user_id))
    conn.commit()
    conn.close()

# ===== БИРЖА =====
def get_all_cards():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, rarity, price, change_24h FROM cards ORDER BY price DESC")
    rows = c.fetchall()
    conn.close()
    return rows

def update_exchange():
    all_cards = get_all_cards()
    if not all_cards:
        return
    anchors = all_cards[:ANCHOR_COUNT]
    remaining = all_cards[ANCHOR_COUNT:]
    rotating = random.sample(remaining, min(EXCHANGE_SIZE - ANCHOR_COUNT, len(remaining)))
    exchange_cache["anchors"] = anchors
    exchange_cache["rotating"] = rotating
    exchange_cache["last_update"] = datetime.now()

def get_exchange_cards():
    if not exchange_cache["last_update"] or \
       datetime.now() - exchange_cache["last_update"] > timedelta(seconds=ROTATION_INTERVAL):
        update_exchange()
    return exchange_cache["anchors"] + exchange_cache["rotating"]

def force_update_exchange():
    update_exchange()

# ===== БОТ И ДИСПЕТЧЕР =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ХЕНДЛЕРЫ =====
@dp.message(Command("start"))
async def start(message: Message):
    create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "🏁 **IndyCard Exchange**\n\nДобро пожаловать!\n"
        "💰 Баланс: 500 💰\n"
        "🎲 Попыток в играх: 3/3ч\n\n"
        "Используй кнопки:",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.message(Command("admin"))
async def admin(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("👑 **Админ-панель**", reply_markup=admin_panel(), parse_mode="Markdown")

@dp.message(Command("setname"))
async def setname(message: Message):
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

@dp.message(Command("buy"))
async def buy(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажи код: /buy PAL")
        return
    code = parts[1].upper()
    card = get_card_info(code)
    if not card:
        await message.answer("❌ Карта не найдена")
        return
    user = get_user(message.from_user.id)
    if user[3] < card[5]:
        await message.answer(f"❌ Нужно {card[5]} 💰")
        return
    update_balance(message.from_user.id, -card[5], "buy", code)
    add_card_to_user(message.from_user.id, code)
    await message.answer(f"✅ {card[1]} ({code}) куплена за {card[5]} 💰")

@dp.message(Command("sell"))
async def sell(message: Message):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("❌ Укажи код: /sell PAL")
        return
    code = parts[1].upper()
    card = get_card_info(code)
    if not card:
        await message.answer("❌ Карта не найдена")
        return
    cards = get_user_cards(message.from_user.id)
    if cards.get(code, 0) < 1:
        await message.answer("❌ У тебя нет этой карты")
        return
    price = int(card[5] * 0.7)
    remove_card_from_user(message.from_user.id, code)
    update_balance(message.from_user.id, price, "sell", code)
    await message.answer(f"✅ {card[1]} ({code}) продана за {price} 💰")

@dp.message(Command("balance"))
async def balance(message: Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 Твой баланс: {user[3]} 💰")

@dp.message(Command("top"))
async def top(message: Message):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT display_name, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    text = "🏆 **Топ-10**\n\n"
    for i, (name, balance) in enumerate(rows, 1):
        text += f"{i}. {name} — {balance} 💰\n"
    await message.answer(text, parse_mode="Markdown")

@dp.message(Command("give"))
async def give_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    parts = message.text.split(maxsplit=2)
    if len(parts) < 3:
        await message.answer("❌ Используй: /give @username 100 (или /give @username PAL)")
        return
    target = parts[1].strip()
    value = parts[2].strip()
    target_id = None
    if target.startswith("@"):
        target = target[1:]
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (target,))
        row = c.fetchone()
        conn.close()
        if not row:
            await message.answer(f"❌ Пользователь @{target} не найден")
            return
        target_id = row[0]
    else:
        try:
            target_id = int(target)
        except:
            await message.answer("❌ Неверный формат")
            return
    if value.isdigit():
        amount = int(value)
        update_balance(target_id, amount, "admin_give")
        await message.answer(f"✅ Выдано {amount} 💰 пользователю {target}")
        return
    card = get_card_info(value.upper())
    if card:
        add_card_to_user(target_id, value.upper())
        await message.answer(f"✅ Выдана карта {card[1]} ({value.upper()}) пользователю {target}")
        return
    await message.answer("❌ Неверный формат")

@dp.message(Command("promo"))
async def promo_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    parts = message.text.split(maxsplit=3)
    if len(parts) < 4:
        await message.answer("❌ Используй: /promo код @username PAL")
        return
    code, target, reward = parts[1], parts[2], parts[3]
    if target.startswith("@"):
        target = target[1:]
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("SELECT user_id FROM users WHERE username = ?", (target,))
        row = c.fetchone()
        conn.close()
        if not row:
            await message.answer(f"❌ Пользователь @{target} не найден")
            return
        user_id = row[0]
    if reward.isdigit():
        update_balance(user_id, int(reward), "promo")
        await message.answer(f"✅ Промокод {code} активирован! Выдано {reward} 💰")
    else:
        card = get_card_info(reward.upper())
        if card:
            add_card_to_user(user_id, reward.upper())
            await message.answer(f"✅ Промокод {code} активирован! Выдана карта {card[1]}")
        else:
            await message.answer("❌ Неверная награда")

# ===== КНОПКИ =====
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(call: CallbackQuery):
    await call.message.edit_text("🏁 **Главное меню**", reply_markup=main_menu(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "my_cards")
async def my_cards(call: CallbackQuery):
    cards = get_user_cards(call.from_user.id)
    if not cards:
        await call.message.edit_text("📭 У тебя пока нет карт", reply_markup=back_to_menu(), parse_mode="Markdown")
        await call.answer()
        return
    text = "🎴 **Мои карты**\n\n"
    total = 0
    for code, qty in cards.items():
        card = get_card_info(code)
        if not card:
            continue
        emoji = get_rarity_emoji(card[4])
        text += f"{emoji} {card[1]} ({code}) ×{qty}\n"
        total += qty
    text += f"\n📊 Всего: {total}"
    await call.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "get_card")
async def get_card(call: CallbackQuery):
    rarities = []
    for rarity, data in RARITIES.items():
        rarities.extend([rarity] * data["chance"])
    selected_rarity = random.choice(rarities)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (selected_rarity,))
    row = c.fetchone()
    conn.close()
    if not row:
        await call.answer("❌ Нет карт", show_alert=True)
        return
    code = row[0]
    add_card_to_user(call.from_user.id, code)
    card = get_card_info(code)
    emoji = get_rarity_emoji(card[4])
    await call.message.edit_text(
        f"🎲 **Получена карта!**\n\n"
        f"{emoji} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {card[4]}\n"
        f"💰 {card[5]} 💰",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "exchange")
async def exchange(call: CallbackQuery):
    user_id = call.from_user.id
    user = get_user(user_id)
    cards = get_exchange_cards()
    if not cards:
        await call.message.edit_text("📭 **Биржа**\n\nНет доступных карт", reply_markup=back_to_menu(), parse_mode="Markdown")
        await call.answer()
        return
    text = "🏦 **Биржа**\n\n"
    text += f"💰 Баланс: {user[3]} 💰\n"
    text += f"🔄 Обновление: каждые 10 минут\n\n"
    text += "📌 **Якорные**\n"
    for code, name, rarity, price, change in cards[:3]:
        emoji = get_rarity_emoji(rarity)
        change_symbol = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        text += f"{emoji} {name} ({code}) — {price} 💰 {change_symbol} {change:.1f}%\n"
    text += "\n🔄 **В ротации**\n"
    for code, name, rarity, price, change in cards[3:]:
        emoji = get_rarity_emoji(rarity)
        change_symbol = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        text += f"{emoji} {name} ({code}) — {price} 💰 {change_symbol} {change:.1f}%\n"
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить", callback_data="exchange_refresh")],
        [InlineKeyboardButton(text="💰 Купить", callback_data="exchange_buy"),
         InlineKeyboardButton(text="💸 Продать", callback_data="exchange_sell")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "exchange_refresh")
async def refresh_exchange(call: CallbackQuery):
    force_update_exchange()
    await call.answer("🔄 Биржа обновлена!")
    await exchange(call)

@dp.callback_query(F.data == "exchange_buy")
async def exchange_buy(call: CallbackQuery):
    await call.message.edit_text(
        "💎 **Покупка карты**\n\nВведи код: `/buy PAL`",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "exchange_sell")
async def exchange_sell(call: CallbackQuery):
    await start_sell_process(call)

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
    if user[3] < 50:
        await call.answer("❌ Нужно 50 💰", show_alert=True)
        return
    update_balance(call.from_user.id, -50, "shop_attempt")
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = game_attempts + 1 WHERE user_id = ?", (call.from_user.id,))
    conn.commit()
    conn.close()
    await call.message.edit_text(f"✅ Куплена попытка!\n💰 Баланс: {user[3] - 50} 💰", reply_markup=back_to_menu())
    await call.answer()

@dp.callback_query(F.data == "shop_card")
async def shop_card(call: CallbackQuery):
    user = get_user(call.from_user.id)
    if user[3] < 100:
        await call.answer("❌ Нужно 100 💰", show_alert=True)
        return
    update_balance(call.from_user.id, -100, "shop_card")
    rarities = []
    for rarity, data in RARITIES.items():
        rarities.extend([rarity] * data["chance"])
    selected_rarity = random.choice(rarities)
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (selected_rarity,))
    row = c.fetchone()
    conn.close()
    if not row:
        await call.answer("❌ Нет карт", show_alert=True)
        return
    code = row[0]
    add_card_to_user(call.from_user.id, code)
    card = get_card_info(code)
    await call.message.edit_text(
        f"🎴 Куплена карта!\n\n{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n💰 {card[5]} 💰",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "games")
async def games(call: CallbackQuery):
    attempts = get_game_attempts(call.from_user.id)
    await call.message.edit_text(
        f"🎮 **Мини-игры**\n\n🎲 Попыток: {attempts}/3 (сброс через 3ч)",
        reply_markup=games_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "profile")
async def profile(call: CallbackQuery):
    user = get_user(call.from_user.id)
    cards = get_user_cards(call.from_user.id)
    total = sum(cards.values())
    attempts = get_game_attempts(call.from_user.id)
    await call.message.edit_text(
        f"👤 **Профиль**\n\nИмя: {user[2]}\n💰 Баланс: {user[3]} 💰\n🎴 Карт: {total}\n🏆 Рейтинг: {user[4]}\n🎲 Попыток: {attempts}",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "about")
async def about(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ **О проекте**\n\nIndyCard Exchange — карточная игра по IndyCar.\n\n@Scanialove\n@Gabriella1488",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== ПРОДАЖА С ЛИСТАНИЕМ =====
async def start_sell_process(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    if not cards:
        await call.message.edit_text("📭 Нет карт для продажи", reply_markup=back_to_menu())
        await call.answer()
        return
    user_sell[user_id] = {"index": 0, "cards": list(cards.keys())}
    await show_sell_card(call.message, user_id)

async def show_sell_card(message, user_id):
    session = user_sell.get(user_id)
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
        [InlineKeyboardButton(text="◀️", callback_data="sell_prev"),
         InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="sell_count"),
         InlineKeyboardButton(text="▶️", callback_data="sell_next")],
        [InlineKeyboardButton(text=f"💰 Продать за {price} 💰", callback_data=f"sell_confirm_{code}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_exchange")]
    ])
    await message.edit_text(
        f"💵 **Продажа**\n\n{emoji} {card[1]} ({code})\n🏁 {card[2]}\n🎴 {card[4]}\n💰 Цена: {card[5]} 💰\n💸 Продажа: {price} 💰\n📦 {qty} шт.\n\n{index+1}/{total}",
        reply_markup=markup,
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "sell_next")
async def sell_next(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_sell:
        await call.answer("❌ Сессия истекла")
        return
    user_sell[user_id]["index"] += 1
    await show_sell_card(call.message, user_id)
    await call.answer()

@dp.callback_query(F.data == "sell_prev")
async def sell_prev(call: CallbackQuery):
    user_id = call.from_user.id
    if user_id not in user_sell:
        await call.answer("❌ Сессия истекла")
        return
    user_sell[user_id]["index"] -= 1
    if user_sell[user_id]["index"] < 0:
        user_sell[user_id]["index"] = 0
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
        await call.answer("❌ Нет карты")
        return
    price = int(card[5] * 0.7)
    remove_card_from_user(user_id, code)
    update_balance(user_id, price, "sell", code)
    remaining = get_user_cards(user_id)
    if not remaining:
        await call.message.edit_text(f"✅ {card[1]} продана за {price} 💰\n💰 Баланс: {get_user(user_id)[3]} 💰", reply_markup=back_to_menu())
        await call.answer()
        return
    user_sell[user_id]["cards"] = list(remaining.keys())
    if user_sell[user_id]["index"] >= len(user_sell[user_id]["cards"]):
        user_sell[user_id]["index"] = 0
    await show_sell_card(call.message, user_id)
    await call.answer()

# ===== МИНИ-ИГРЫ =====
@dp.callback_query(F.data == "game_guess_driver")
async def game_guess_driver(call: CallbackQuery):
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
    await call.message.edit_text(f"🎲 **Угадай пилота**\n\nПодсказка: {team}\n\nКто это?", reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("guess_"))
async def guess_result(call: CallbackQuery):
    parts = call.data.split("_")
    correct, answer = parts[1], parts[2]
    if correct == answer:
        win = 50
        update_balance(call.from_user.id, win, "game_guess")
        result = f"✅ Правильно! +{win} 💰"
    else:
        result = f"❌ Неправильно! Это был {correct}"
    user = get_user(call.from_user.id)
    await call.message.edit_text(f"🎲 **Результат**\n\n{result}\n\n💰 Баланс: {user[3]} 💰", reply_markup=back_to_menu(), parse_mode="Markdown")
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
    await call.message.edit_text("🎲 **Бросок кубиков**\n\nВыбери ставку (х2 при 6+, х3 при 11+):", reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("dice_"))
async def dice_result(call: CallbackQuery):
    bet = int(call.data.split("_")[1])
    user = get_user(call.from_user.id)
    if user[3] < bet:
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
    update_balance(call.from_user.id, win, "game_dice")
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"🎲 **Результат**\n\n{d1} + {d2} = {total}\n"
        f"{'🎉 Выигрыш: ' + str(win) if win > 0 else '❌ Проигрыш: ' + str(-win)}\n"
        f"💰 Баланс: {user[3]} 💰",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== АДМИН =====
@dp.callback_query(F.data == "admin_add")
async def admin_add(call: CallbackQuery):
    await call.message.edit_text(
        "➕ Введите: `code|name|team|number|rarity|price|year|image`",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
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
    await call.message.edit_text(text[:4000], reply_markup=back_to_menu(), parse_mode="Markdown")
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
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_promo")
async def admin_promo(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 **Промокод**\n\nИспользуй: `/promo НАЗВАНИЕ @username PAL`",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== ФОНОВОЕ ОБНОВЛЕНИЕ ЦЕН =====
async def price_updater():
    while True:
        await asyncio.sleep(ROTATION_INTERVAL)
        try:
            conn = sqlite3.connect("indycard.db")
            c = conn.cursor()
            c.execute("SELECT code, price FROM cards")
            rows = c.fetchall()
            for code, price in rows:
                change = random.uniform(-5, 5)
                new_price = int(price * (1 + change / 100))
                if new_price < 10:
                    new_price = 10
                c.execute("UPDATE cards SET price = ?, change_24h = ? WHERE code = ?",
                         (new_price, change, code))
            conn.commit()
            conn.close()
            force_update_exchange()
            logger.info("✅ Цены и биржа обновлены")
        except Exception as e:
            logger.error(f"Price updater error: {e}")

# ===== ВЕБХУК =====
async def on_startup(app: web.Application):
    asyncio.create_task(price_updater())
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
