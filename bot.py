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

# ===== БАЗА =====
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
                conn = sqlite3.connect("indycard.db")
                c = conn.cursor()
                c.execute("UPDATE users SET game_attempts = 3, last_game_attempt = ? WHERE user_id = ?",
                         (datetime.now().isoformat(), user_id))
                conn.commit()
                conn.close()
                return 3
        except:
            pass
    return attempts

def use_game_attempt(user_id):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE users SET game_attempts = game_attempts - 1, last_game_attempt = ? WHERE user_id = ?",
              (datetime.now().isoformat(), user_id))
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

# ===== СЕССИИ =====
user_market_session = {}  # {user_id: {"cards": [], "index": 0, "price": 0}}
admin_price_session = {}  # {user_id: code}
user_sell_session = {}    # {user_id: {"cards": [], "index": 0}}

# ===== КЛАВИАТУРЫ =====
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
         InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card")],
        [InlineKeyboardButton(text="🏦 Биржа", callback_data="exchange"),
         InlineKeyboardButton(text="📊 Рынок игроков", callback_data="player_market")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🏪 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🎁 Промокод", callback_data="promo_enter"),
         InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about")]
    ])

def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def games_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Угадай пилота", callback_data="game_guess")],
        [InlineKeyboardButton(text="🎲 Бросок кубиков", callback_data="game_dice")],
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

# ===== БОТ =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== СТАРТ (без команд) =====
@dp.message()
async def start(message: Message):
    if message.text == "/start":
        create_user(message.from_user.id, message.from_user.username)
        await message.answer(
            "🏁 **IndyCard Exchange**\n\n"
            "💰 Баланс: 500 💰\n"
            "🎲 Попыток: 3/3ч\n\n"
            "Выбирай действие:",
            reply_markup=main_menu(),
            parse_mode="Markdown"
        )
    else:
        # Игнорируем все сообщения, кроме /start
        await message.answer("Используй кнопки!", reply_markup=main_menu())

@dp.message(Command("admin"))
async def admin_command(message: Message):
    if not is_admin(message.from_user.id):
        await message.answer("⛔ Нет доступа")
        return
    await message.answer("👑 **Админ-панель**", reply_markup=admin_menu(), parse_mode="Markdown")

# ===== КНОПКИ =====
@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(call: CallbackQuery):
    await call.message.edit_text(
        "🏁 **Главное меню**",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "my_cards")
async def my_cards(call: CallbackQuery):
    cards = get_user_cards(call.from_user.id)
    if not cards:
        await call.message.edit_text("📭 Нет карт", reply_markup=back_menu(), parse_mode="Markdown")
        await call.answer()
        return
    
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, "EXCLUSIVE": 3, "RARE": 4, "REGULAR": 5}
    sorted_cards = sorted(cards.items(), key=lambda x: rarity_order.get(get_card_info(x[0])[4], 99))
    
    text = "🎴 **Мои карты**\n\n"
    for code, qty in sorted_cards:
        card = get_card_info(code)
        if not card:
            continue
        emoji = get_rarity_emoji(card[4])
        text += f"{emoji} {card[1]} ({code}) ×{qty}\n"
    
    text += f"\n📊 Всего: {sum(cards.values())} карт"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💸 Продать карту", callback_data="sell_menu")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

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
    c.execute("SELECT code, name, rarity, price, change_24h FROM cards ORDER BY price DESC LIMIT 10")
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
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for code, name, rarity, price, change in rows:
        markup.inline_keyboard.append([
            InlineKeyboardButton(text=f"💎 {name} ({code}) — {price} 💰", callback_data=f"buy_{code}")
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

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

# ===== ВЫСТАВЛЕНИЕ НА РЫНОК =====
@dp.callback_query(F.data == "market_sell")
async def market_sell_start(call: CallbackQuery):
    user_id = call.from_user.id
    cards = get_user_cards(user_id)
    if not cards:
        await call.message.edit_text("📭 Нет карт для продажи", reply_markup=back_menu())
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
    await call.message.edit_text(f"✅ Попытка куплена!\n💰 Баланс: {user[2] - 50}", reply_markup=back_menu())
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
        card = get_card_info(code)
        await call.message.edit_text(
            f"🎴 Куплена карта!\n\n{get_rarity_emoji(card[4])} {card[1]} ({card[0]})",
            reply_markup=back_menu(),
            parse_mode="Markdown"
        )
    else:
        await call.message.edit_text("❌ Нет карт", reply_markup=back_menu())
    await call.answer()

@dp.callback_query(F.data == "games")
async def games(call: CallbackQuery):
    attempts = get_game_attempts(call.from_user.id)
    await call.message.edit_text(
        f"🎮 **Мини-игры**\n\n🎲 Попыток: {attempts}/3\n\nВыбери игру:",
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
        f"👤 **Профиль**\n\n"
        f"Имя: {user[1] or user[3]}\n"
        f"💰 Баланс: {user[2]} 💰\n"
        f"🎴 Карт: {total}\n"
        f"🎲 Попыток: {attempts}",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "about")
async def about(call: CallbackQuery):
    await call.message.edit_text(
        "ℹ️ **О проекте**\n\nIndyCard Exchange — карточная игра по IndyCar.\n\n@Scanialove\n@Gabriella1488",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "promo_enter")
async def promo_enter(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 **Активация промокода**\n\nВведи код в сообщении",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== ПРОМОКОД ЧЕРЕЗ СООБЩЕНИЕ =====
@dp.message()
async def handle_promo_message(message: Message):
    user_id = message.from_user.id
    text = message.text.strip()
    
    # Проверяем, не является ли это промокодом
    if len(text) == 8 and text.isalnum():
        result = use_promo(text.upper(), user_id)
        await message.answer(f"🎁 **Результат**\n\n{result['message']}", parse_mode="Markdown")
    else:
        # Игнорируем всё остальное
        pass

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
    user = get_user(call.from_user.id)
    await call.message.edit_text(
        f"🎲 **Результат**\n\n{d1} + {d2} = {total}\n"
        f"{'🎉 Выигрыш: ' + str(win) if win > 0 else '❌ Проигрыш: ' + str(-win)}\n"
        f"💰 Баланс: {user[2]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== АДМИН =====
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
        "💵 Введите сумму монет для промокода в сообщении",
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

# ===== ФОН =====
async def update_prices():
    while True:
        await asyncio.sleep(600)
        try:
            conn = sqlite3.connect("indycard.db")
            c = conn.cursor()
            c.execute("SELECT code FROM cards")
            rows = c.fetchall()
            for row in rows:
                change = random.uniform(-5, 5)
                update_card_price(row[0], change)
            conn.close()
            logger.info("✅ Цены обновлены")
        except Exception as e:
            logger.error(f"Price update error: {e}")

# ===== ВЕБХУК =====
async def on_startup(app: web.Application):
    asyncio.create_task(update_prices())
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
