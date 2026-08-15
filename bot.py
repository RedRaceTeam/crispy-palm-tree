# bot.py — IndyCard бот с вебхуком (aiogram 3)

import os
import logging
import sqlite3
import random
import string
import json
from datetime import datetime, timedelta

from aiohttp import web
from aiogram import Bot, Dispatcher, types, F, Router
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from dotenv import load_dotenv

from data.drivers import DRIVERS
from data.winners import WINNERS

load_dotenv()

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
BASE_WEBHOOK_URL = os.getenv("BASE_WEBHOOK_URL")  # https://your-domain.com
WEBHOOK_PATH = "/webhook"
WEBHOOK_SECRET = os.getenv("WEBHOOK_SECRET", "my-secret")  # проверка, что запросы от Telegram [citation:8][citation:10]
WEB_SERVER_HOST = "0.0.0.0"
WEB_SERVER_PORT = int(os.getenv("PORT", 8000))
ADMIN_IDS = [7025868617, 7946032603]

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== РЕДКОСТИ =====
RARITIES = {
    "REGULAR": {"emoji": "🟢", "rating": 10, "chance": 50, "name": "Обычная"},
    "RARE": {"emoji": "⭐", "rating": 25, "chance": 25, "name": "Редкая"},
    "EXCLUSIVE": {"emoji": "🔮", "rating": 40, "chance": 15, "name": "Эксклюзив"},
    "LEGENDARY": {"emoji": "💎", "rating": 60, "chance": 7, "name": "Легендарная"},
    "INDY_EDITION": {"emoji": "🏁", "rating": 100, "chance": 2, "name": "Indy Edition"},
    "ULTIMATE": {"emoji": "👑", "rating": 150, "chance": 1, "name": "Ультимативная"},
}

# ===== СЕССИИ =====
user_card_pages = {}
user_sell_session = {}
user_bet_session = {}
admin_price_session = {}

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
    
    c.execute("""CREATE TABLE IF NOT EXISTS price_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        card_code TEXT,
        price INTEGER,
        change_percent REAL,
        change_reason TEXT,
        timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS market_state (
        id INTEGER PRIMARY KEY,
        last_update DATE,
        market_data TEXT
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS race_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        date DATE,
        event_name TEXT,
        race_data TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    )""")
    
    c.execute("""CREATE TABLE IF NOT EXISTS daily_bonus (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        date DATE,
        streak INTEGER,
        bonus INTEGER,
        UNIQUE(user_id, date)
    )""")
    
    conn.commit()
    conn.close()
    logger.info("✅ База данных инициализирована")

def seed_data():
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    
    for code, data in DRIVERS.items():
        c.execute("""INSERT OR IGNORE INTO cards 
            (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, data["name"], data["team"], data.get("number", 0),
             data["rarity"], data["price"],
             RARITIES.get(data["rarity"], {}).get("rating", 10),
             2026, data.get("image", "")))
    
    for winner in WINNERS:
        code = f"WIN_{winner['driver'][:3].upper()}_{winner['year']}"
        c.execute("""INSERT OR IGNORE INTO cards 
            (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code, winner["driver"], "Indy 500 Winner", 0,
             winner.get("rarity", "INDY_EDITION"), winner.get("price", 500),
             RARITIES.get(winner.get("rarity", "INDY_EDITION"), {}).get("rating", 100),
             winner["year"], ""))
    
    conn.commit()
    conn.close()
    logger.info("✅ Данные загружены")

init_db()
seed_data()

# ===== ФУНКЦИИ БАЗЫ =====
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

def get_rarity_name(rarity):
    return RARITIES.get(rarity, {}).get("name", "Обычная")

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

# ===== ПРОМОКОДЫ =====
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
        return {"status": "error", "message": "❌ Ты уже активировал этот промокод"}
    
    c.execute("SELECT reward_type, reward_value, max_uses, used FROM promocodes WHERE code = ?", (code,))
    row = c.fetchone()
    if not row:
        conn.close()
        return {"status": "error", "message": "❌ Промокод не найден"}
    
    reward_type, reward_value, max_uses, used = row
    if used >= max_uses:
        conn.close()
        return {"status": "error", "message": "❌ Промокод использован"}
    
    if reward_type == "coins":
        amount = int(reward_value)
        update_balance(user_id, amount, "promo")
        result = {"status": "success", "message": f"✅ Получено {amount} 💰"}
    else:
        card_code = reward_value
        add_card_to_user(user_id, card_code)
        card = get_card_info(card_code)
        result = {"status": "success", "message": f"✅ Получена карта {card[1]} ({card[0]})"}
    
    c.execute("UPDATE promocodes SET used = used + 1 WHERE code = ?", (code,))
    c.execute("INSERT INTO promo_usage (code, user_id) VALUES (?, ?)", (code, user_id))
    conn.commit()
    conn.close()
    return result

# ===== ЕЖЕДНЕВНЫЙ БОНУС =====
def get_daily_bonus(user_id):
    today = datetime.now().date()
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    
    c.execute("SELECT 1 FROM daily_bonus WHERE user_id = ? AND date = ?", (user_id, today))
    if c.fetchone():
        conn.close()
        return None
    
    yesterday = today - timedelta(days=1)
    c.execute("SELECT streak FROM daily_bonus WHERE user_id = ? AND date = ?", (user_id, yesterday))
    row = c.fetchone()
    streak = row[0] + 1 if row else 1
    
    bonus = 50 + (streak - 1) * 10
    if streak >= 7:
        bonus += 100
    
    c.execute("UPDATE users SET balance = balance + ? WHERE user_id = ?", (bonus, user_id))
    c.execute("SELECT balance FROM users WHERE user_id = ?", (user_id,))
    new_balance = c.fetchone()[0]
    
    c.execute("INSERT INTO daily_bonus (user_id, date, streak, bonus) VALUES (?, ?, ?, ?)",
              (user_id, today, streak, bonus))
    c.execute("INSERT INTO transactions (user_id, type, amount, balance_after) VALUES (?, 'daily_bonus', ?, ?)",
              (user_id, bonus, new_balance))
    
    conn.commit()
    conn.close()
    return {"bonus": bonus, "streak": streak}

# ===== РЫНОЧНЫЙ ДВИЖОК =====
class MarketEngine:
    def __init__(self):
        self.conn = sqlite3.connect("indycard.db")
        self.c = self.conn.cursor()
    
    def update_all_prices(self):
        today = datetime.now().date()
        
        self.c.execute("SELECT last_update FROM market_state WHERE id = 1")
        row = self.c.fetchone()
        if row and row[0] == today:
            return {"status": "already_updated"}
        
        self.c.execute("SELECT code, price, rarity FROM cards")
        cards = self.c.fetchall()
        
        changes = {}
        
        for code, price, rarity in cards:
            race_factor = self._get_race_factor(code)
            demand_factor = self._get_demand_factor(code)
            rarity_factor = self._get_rarity_factor(rarity, code)
            volatility = random.uniform(-5, 5)
            
            total_change = race_factor + demand_factor + rarity_factor + volatility
            total_change = max(-30, min(50, total_change))
            
            new_price = int(price * (1 + total_change / 100))
            new_price = max(10, min(new_price, 100000))
            
            self.c.execute("UPDATE cards SET price = ?, change_24h = ? WHERE code = ?",
                          (new_price, round(total_change, 1), code))
            
            self.c.execute("""INSERT INTO price_history 
                (card_code, price, change_percent, change_reason)
                VALUES (?, ?, ?, ?)""",
                (code, new_price, round(total_change, 1),
                 self._get_change_reason(total_change, race_factor, demand_factor, rarity_factor)))
            
            changes[code] = {
                "old_price": price,
                "new_price": new_price,
                "change": round(total_change, 1)
            }
        
        self.c.execute("INSERT OR REPLACE INTO market_state (id, last_update, market_data) VALUES (1, ?, ?)",
                      (today, json.dumps(changes)))
        
        self.conn.commit()
        return {"status": "success", "changes": changes}
    
    def _get_race_factor(self, card_code):
        self.c.execute("SELECT race_data FROM race_events ORDER BY date DESC LIMIT 3")
        races = self.c.fetchall()
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
    
    def _get_demand_factor(self, card_code):
        self.c.execute("""SELECT COUNT(*) FROM transactions 
            WHERE code = ? AND type IN ('market_buy', 'buy')
            AND timestamp > datetime('now', '-7 days')""", (card_code,))
        sales = self.c.fetchone()[0]
        
        self.c.execute("SELECT COUNT(*) FROM market_listings WHERE card_code = ? AND status = 'active'", (card_code,))
        listings = self.c.fetchone()[0]
        
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
    
    def _get_rarity_factor(self, rarity, card_code):
        bonuses = {"REGULAR": 0, "RARE": 2, "EXCLUSIVE": 5, "LEGENDARY": 10, "INDY_EDITION": 15, "ULTIMATE": 20}
        base = bonuses.get(rarity, 0)
        
        self.c.execute("SELECT SUM(quantity) FROM user_cards WHERE code = ?", (card_code,))
        total = self.c.fetchone()[0] or 0
        
        if total < 10:
            scarcity = 15
        elif total < 50:
            scarcity = 10
        elif total < 100:
            scarcity = 5
        else:
            scarcity = 0
        
        return base + scarcity
    
    def _get_change_reason(self, total, race, demand, rarity):
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

# ===== КЛАВИАТУРЫ =====
def main_menu(user_id=None):
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
         InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card")],
        [InlineKeyboardButton(text="🏦 Биржа", callback_data="exchange"),
         InlineKeyboardButton(text="📊 Рынок", callback_data="player_market")],
        [InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
         InlineKeyboardButton(text="🏪 Магазин", callback_data="shop")],
        [InlineKeyboardButton(text="🎁 Бонус", callback_data="daily_bonus"),
         InlineKeyboardButton(text="⚔️ PvP", callback_data="pvp_menu")],
        [InlineKeyboardButton(text="🎁 Промокод", callback_data="promo_enter"),
         InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about")]
    ])
    
    if user_id and is_admin(user_id):
        markup.inline_keyboard.append([
            InlineKeyboardButton(text="👑 INDY Admin", callback_data="admin_panel")
        ])
    
    return markup

def back_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def admin_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="📊 Обновить цены", callback_data="admin_update_prices")],
        [InlineKeyboardButton(text="🏁 Добавить гонку", callback_data="admin_add_race")],
        [InlineKeyboardButton(text="💰 Управление ценами", callback_data="admin_price")],
        [InlineKeyboardButton(text="🎁 Создать промокод", callback_data="admin_promo")],
        [InlineKeyboardButton(text="🎴 Все карты", callback_data="admin_all_cards")],
        [InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def shop_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎲 Попытка (50 💰)", callback_data="shop_attempt")],
        [InlineKeyboardButton(text="🎴 Случайная карта (100 💰)", callback_data="shop_card")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

def pvp_bet_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💰 Деньги", callback_data="pvp_bet_money")],
        [InlineKeyboardButton(text="🎴 Карта", callback_data="pvp_bet_card")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="pvp_menu")]
    ])

def pvp_money_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="10 💰", callback_data="pvp_money_10"),
         InlineKeyboardButton(text="25 💰", callback_data="pvp_money_25")],
        [InlineKeyboardButton(text="50 💰", callback_data="pvp_money_50"),
         InlineKeyboardButton(text="100 💰", callback_data="pvp_money_100")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="pvp_menu")]
    ])

def admin_promo_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="💎 Карта", callback_data="admin_promo_card")],
        [InlineKeyboardButton(text="💰 Монеты", callback_data="admin_promo_coins")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")]
    ])

# ===== БОТ =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ОБРАБОТЧИКИ =====
@dp.message(Command("start"))
async def start_command(message: Message):
    create_user(message.from_user.id, message.from_user.username)
    await message.answer(
        "🏁 **IndyCard Exchange**\n\n"
        "💰 Баланс: 500 💰\n"
        "🎲 Попыток: 3/3ч\n\n"
        "Выбирай действие:",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@dp.message()
async def handle_messages(message: Message):
    text = message.text.strip()
    if len(text) == 8 and text.isalnum():
        result = use_promo(text.upper(), message.from_user.id)
        await message.answer(f"🎁 **Результат**\n\n{result['message']}", parse_mode="Markdown")

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
        "🎴 Собирай карты пилотов IndyCar\n"
        "🏦 Торгуй на бирже и рынке\n"
        "⚔️ Играй в PvP на кубиках\n\n"
        "Разработчики: @Scanialove, @Gabriella1488",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "promo_enter")
async def promo_enter(call: CallbackQuery):
    await call.message.edit_text(
        "🎁 **Введите промокод**\n\nОтправь код в сообщении (8 символов)",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "daily_bonus")
async def daily_bonus(call: CallbackQuery):
    user_id = call.from_user.id
    result = get_daily_bonus(user_id)
    
    if not result:
        await call.answer("❌ Ты уже получил бонус сегодня!", show_alert=True)
        return
    
    emoji = "🔥" if result["streak"] >= 7 else "🎁"
    await call.message.edit_text(
        f"{emoji} **Ежедневный бонус!**\n\n"
        f"День {result['streak']} подряд\n"
        f"+{result['bonus']} 💰\n\n"
        f"💰 Баланс: {get_user(user_id)[2]} 💰",
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
        [InlineKeyboardButton(text="◀️", callback_data="cards_prev"),
         InlineKeyboardButton(text=f"{page+1}/{total_pages}", callback_data="cards_page"),
         InlineKeyboardButton(text="▶️", callback_data="cards_next")],
        [InlineKeyboardButton(text="💸 Продать", callback_data="sell_menu")],
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
    card = get_card_info(code)
    
    await call.message.edit_text(
        f"🎲 **Получена карта!**\n\n"
        f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {get_rarity_name(card[4])}\n"
        f"💰 {card[5]} 💰",
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
        [InlineKeyboardButton(text="◀️", callback_data="sell_prev"),
         InlineKeyboardButton(text=f"{index+1}/{total}", callback_data="sell_count"),
         InlineKeyboardButton(text="▶️", callback_data="sell_next")],
        [InlineKeyboardButton(text=f"💰 Продать за {price} 💰", callback_data=f"sell_confirm_{code}")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    
    await message.edit_text(
        f"💵 **Продажа карты**\n\n"
        f"{emoji} {card[1]} ({card[0]})\n"
        f"🏁 {card[2]}\n"
        f"🎴 {get_rarity_name(card[4])}\n"
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
    
    await call.message.edit_text(
        f"✅ {card[1]} ({code}) продана за {price} 💰\n"
        f"💰 Новый баланс: {get_user(user_id)[2]} 💰",
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
    
    text = "🏦 **Биржа**\n\n💰 Баланс: {} 💰\n\n".format(user[2])
    for code, name, rarity, price, change in rows:
        emoji = get_rarity_emoji(rarity)
        arrow = "📈" if change > 0 else "📉" if change < 0 else "➡️"
        text += f"{emoji} {name} ({code}) — {price} 💰 {arrow} {change}%\n"
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔄 Обновить цены", callback_data="exchange_refresh")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])
    for code, name, rarity, price, change in rows[:5]:
        markup.inline_keyboard.insert(0, [
            InlineKeyboardButton(text=f"💎 {name} ({code}) — {price} 💰", callback_data=f"buy_{code}")
        ])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "exchange_refresh")
async def exchange_refresh(call: CallbackQuery):
    engine = MarketEngine()
    result = engine.update_all_prices()
    
    if result["status"] == "already_updated":
        await call.answer("⏰ Цены уже обновлены сегодня!")
    else:
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
    
    await call.message.edit_text(
        f"✅ {card[1]} ({code}) куплена за {card[5]} 💰\n"
        f"💰 Новый баланс: {get_user(user_id)[2]} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "player_market")
async def player_market(call: CallbackQuery):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT id, user_id, card_code, price FROM market_listings WHERE status = 'active'")
    listings = c.fetchall()
    conn.close()
    
    if not listings:
        await call.message.edit_text(
            "📊 **Рынок игроков**\n\nНа рынке пока нет карт.",
            reply_markup=back_menu(),
            parse_mode="Markdown"
        )
        await call.answer()
        return
    
    text = "📊 **Рынок игроков**\n\n"
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    
    for listing_id, user_id, card_code, price in listings:
        card = get_card_info(card_code)
        if not card:
            continue
        seller = get_user(user_id)
        seller_name = seller[1] or seller[3] or "Неизвестно"
        emoji = get_rarity_emoji(card[4])
        text += f"{emoji} {card[1]} ({card[0]}) — {price} 💰 (от @{seller_name})\n"
        markup.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"💎 Купить {card[1]} за {price} 💰",
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
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE market_listings SET status = 'sold' WHERE id = ?", (listing_id,))
    conn.commit()
    conn.close()
    
    await call.message.edit_text(
        f"✅ Покупка совершена!\n\nКарта {card_code} куплена за {price} 💰",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
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
        card = get_card_info(code)
        await call.message.edit_text(
            f"🎴 Куплена карта!\n\n"
            f"{get_rarity_emoji(card[4])} {card[1]} ({card[0]})",
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
    
    await call.message.edit_text(
        f"👤 **Профиль**\n\n"
        f"Имя: {user[1] or user[3]}\n"
        f"💰 Баланс: {user[2]} 💰\n"
        f"🎴 Карт: {total}\n"
        f"🏆 Рейтинг: {user[4]}\n"
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
        "⚔️ **PvP Кубики**\n\nСоздай битву или присоединись к существующей.",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "pvp_create")
async def pvp_create(call: CallbackQuery):
    await call.message.edit_text(
        "⚔️ **Создание битвы**\n\nЧто ставишь?",
        reply_markup=pvp_bet_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "pvp_bet_money")
async def pvp_bet_money(call: CallbackQuery):
    await call.message.edit_text(
        "💰 **Выбери сумму ставки:**",
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
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("INSERT INTO pvp_battles (player1_id, bet_type, bet_value, status) VALUES (?, 'money', ?, 'waiting')",
              (user_id, str(amount)))
    battle_id = c.lastrowid
    conn.commit()
    conn.close()
    
    await call.message.edit_text(
        f"⚔️ **Битва создана!**\n\nID: {battle_id}\nСтавка: {amount} 💰\n\nДай этот ID другу: `{battle_id}`",
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
                    text=f"{get_rarity_emoji(card[4])} {card[1]} ×{qty}",
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
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("INSERT INTO pvp_battles (player1_id, bet_type, bet_value, status) VALUES (?, 'card', ?, 'waiting')",
              (user_id, code))
    battle_id = c.lastrowid
    conn.commit()
    conn.close()
    
    await call.message.edit_text(
        f"⚔️ **Битва создана!**\n\nID: {battle_id}\nСтавка: карта {get_card_info(code)[1]}\n\nДай этот ID другу: `{battle_id}`",
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
            InlineKeyboardButton(text=f"⚔️ Присоединиться к {battle_id}", callback_data=f"pvp_join_{battle_id}")
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="pvp_menu")])
    
    await call.message.edit_text(text, reply_markup=markup, parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data.startswith("pvp_join_"))
async def pvp_join(call: CallbackQuery):
    battle_id = int(call.data.replace("pvp_join_", ""))
    player2_id = call.from_user.id
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT player1_id, bet_type, bet_value FROM pvp_battles WHERE id = ? AND status = 'waiting'", (battle_id,))
    battle = c.fetchone()
    conn.close()
    
    if not battle:
        await call.answer("❌ Битва не найдена", show_alert=True)
        return
    
    player1_id, bet_type, bet_value = battle
    
    if player1_id == player2_id:
        await call.answer("❌ Нельзя присоединиться к своей битве", show_alert=True)
        return
    
    if bet_type == "money":
        amount = int(bet_value)
        user2 = get_user(player2_id)
        if user2[2] < amount:
            await call.answer(f"❌ Нужно {amount} 💰", show_alert=True)
            return
    else:
        user2_cards = get_user_cards(player2_id)
        if user2_cards.get(bet_value, 0) < 1:
            await call.answer("❌ У тебя нет этой карты", show_alert=True)
            return
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE pvp_battles SET player2_id = ?, status = 'active' WHERE id = ?", (player2_id, battle_id))
    conn.commit()
    conn.close()
    
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
    
    if winner_id:
        if bet_type == "money":
            amount = int(bet_value)
            loser_id = player2_id if winner_id == player1_id else player1_id
            update_balance(loser_id, -amount, "pvp_loss")
            update_balance(winner_id, amount, "pvp_win")
        else:
            loser_id = player2_id if winner_id == player1_id else player1_id
            remove_card_from_user(loser_id, bet_value)
            add_card_to_user(winner_id, bet_value)
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE pvp_battles SET status = 'finished', winner_id = ? WHERE id = ?", (winner_id, battle_id))
    conn.commit()
    conn.close()
    
    await call.message.edit_text(
        f"⚔️ **Результат битвы {battle_id}**\n\n"
        f"Игрок 1: {d1_p1} + {d2_p1} = {total_p1}\n"
        f"Игрок 2: {d1_p2} + {d2_p2} = {total_p2}\n\n"
        f"{'🏆 Победил Игрок 1!' if winner_id == player1_id else '🏆 Победил Игрок 2!' if winner_id else '🤝 Ничья!'}",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== АДМИН-ПАНЕЛЬ =====
@dp.callback_query(F.data == "admin_panel")
async def admin_panel(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await call.message.edit_text(
        "👑 **INDY Admin**\n\n🏁 **Админ-панель**\n\nВыберите действие:",
        reply_markup=admin_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_update_prices")
async def admin_update_prices(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await call.message.edit_text("🔄 **Обновление цен...**", parse_mode="Markdown")
    
    engine = MarketEngine()
    result = engine.update_all_prices()
    
    if result["status"] == "already_updated":
        await call.message.edit_text(
            "⏰ **Цены уже обновлены сегодня!**",
            reply_markup=back_menu(),
            parse_mode="Markdown"
        )
        await call.answer()
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
    
    await call.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_all_cards")
async def admin_all_cards(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("""
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
    """)
    cards = c.fetchall()
    conn.close()
    
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
    
    await call.message.edit_text(text, reply_markup=back_menu(), parse_mode="Markdown")
    await call.answer()

@dp.callback_query(F.data == "admin_stats")
async def admin_stats(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    
    c.execute("SELECT COUNT(*) FROM users")
    users = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM cards")
    cards = c.fetchone()[0]
    
    c.execute("SELECT SUM(quantity) FROM user_cards")
    total = c.fetchone()[0] or 0
    
    c.execute("SELECT SUM(balance) FROM users")
    total_balance = c.fetchone()[0] or 0
    
    c.execute("SELECT COUNT(*) FROM market_listings WHERE status = 'active'")
    listings = c.fetchone()[0]
    
    c.execute("SELECT COUNT(*) FROM pvp_battles WHERE status = 'finished'")
    battles = c.fetchone()[0]
    
    conn.close()
    
    await call.message.edit_text(
        f"📊 **Статистика**\n\n"
        f"👥 Пользователей: {users}\n"
        f"🎴 Карт: {cards}\n"
        f"📦 У игроков: {total}\n"
        f"💰 Всего монет: {total_balance}\n"
        f"📊 Активных лотов: {listings}\n"
        f"⚔️ PvP битв: {battles}",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "admin_promo")
async def admin_promo_start(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
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
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for code, name, rarity in rows:
        markup.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{get_rarity_emoji(rarity)} {name} ({code})",
                callback_data=f"promo_card_{code}"
            )
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_promo")])
    
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
        "💵 **Введите сумму монет**\n\nОтправь число в сообщении",
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
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT code, name, rarity, price FROM cards ORDER BY price DESC LIMIT 20")
    rows = c.fetchall()
    conn.close()
    
    markup = InlineKeyboardMarkup(inline_keyboard=[])
    for code, name, rarity, price in rows:
        markup.inline_keyboard.append([
            InlineKeyboardButton(
                text=f"{get_rarity_emoji(rarity)} {name} ({code}) — {price} 💰",
                callback_data=f"price_edit_{code}"
            )
        ])
    markup.inline_keyboard.append([InlineKeyboardButton(text="🔙 Назад", callback_data="admin_panel")])
    
    await call.message.edit_text(
        "💰 **Управление ценами**\n\nВыбери карту:",
        reply_markup=markup,
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data.startswith("price_edit_"))
async def price_edit(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    code = call.data.replace("price_edit_", "")
    card = get_card_info(code)
    if not card:
        await call.answer("❌ Карта не найдена")
        return
    
    admin_price_session[call.from_user.id] = code
    
    markup = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔽 -100", callback_data=f"price_change_-100"),
         InlineKeyboardButton(text="🔼 +100", callback_data=f"price_change_100")],
        [InlineKeyboardButton(text="🔽 -50", callback_data=f"price_change_-50"),
         InlineKeyboardButton(text="🔼 +50", callback_data=f"price_change_50")],
        [InlineKeyboardButton(text="🔽 -10", callback_data=f"price_change_-10"),
         InlineKeyboardButton(text="🔼 +10", callback_data=f"price_change_10")],
        [InlineKeyboardButton(text="🔙 Назад", callback_data="admin_price")]
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
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
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
    
    new_price = max(10, card[5] + change)
    
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE cards SET price = ? WHERE code = ?", (new_price, code))
    conn.commit()
    conn.close()
    
    await call.answer(f"✅ Цена изменена: {card[5]} → {new_price} 💰", show_alert=True)
    await price_edit(call)

@dp.callback_query(F.data == "admin_add_race")
async def admin_add_race(call: CallbackQuery):
    if not is_admin(call.from_user.id):
        await call.answer("⛔ Доступ запрещён!", show_alert=True)
        return
    
    await call.message.edit_text(
        "🏁 **Добавление гонки**\n\n"
        "Введите данные в формате:\n"
        "`название|победитель|подиум|поул|dnf`\n\n"
        "Пример:\n"
        "`Indy500|PAL|NEW,OWA|DIX|ERI,GRO`",
        reply_markup=back_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.message()
async def handle_add_race(message: Message):
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
        
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("INSERT INTO race_events (date, event_name, race_data) VALUES (?, ?, ?)",
                  (datetime.now().date(), event_name, json.dumps(race_data)))
        conn.commit()
        conn.close()
        
        engine = MarketEngine()
        engine.update_all_prices()
        
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

# ===== НАСТРОЙКА ВЕБХУКА =====
async def on_startup(bot: Bot):
    """Установка вебхука при старте [citation:8][citation:10]"""
    await bot.set_webhook(
        url=f"{BASE_WEBHOOK_URL}{WEBHOOK_PATH}",
        secret_token=WEBHOOK_SECRET
    )
    logger.info(f"✅ Вебхук установлен: {BASE_WEBHOOK_URL}{WEBHOOK_PATH}")

async def on_shutdown(bot: Bot):
    """Удаление вебхука при остановке [citation:8]"""
    await bot.delete_webhook()
    logger.info("❌ Вебхук удалён")

# ===== ЗАПУСК =====
def main():
    """Запуск бота в режиме вебхука [citation:8][citation:12]"""
    if not BASE_WEBHOOK_URL:
        logger.info("🚀 Запуск в режиме поллинга (локально)")
        dp.run_polling(bot)
        return
    
    logger.info(f"🚀 Запуск в режиме вебхука на порту {WEB_SERVER_PORT}")
    
    app = web.Application()
    
    # Регистрация обработчика вебхука [citation:8][citation:12]
    SimpleRequestHandler(
        dispatcher=dp,
        bot=bot,
        secret_token=WEBHOOK_SECRET,
    ).register(app, path=WEBHOOK_PATH)
    
    # Настройка приложения (on_startup/on_shutdown) [citation:8][citation:12]
    setup_application(app, dp, bot=bot)
    
    # Запуск aiohttp сервера
    web.run_app(app, host=WEB_SERVER_HOST, port=WEB_SERVER_PORT)

if __name__ == "__main__":
    main() 
