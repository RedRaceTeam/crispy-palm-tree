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

# ===== ЛОГИРОВАНИЕ =====
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== КОНФИГ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8000))
ADMIN_IDS = [7025868617, 7946032603]

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

# ===== ФУНКЦИИ БД =====
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


def update_card_price(code, new_price):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("UPDATE cards SET price = ? WHERE code = ?", (new_price, code))
    conn.commit()
    conn.close()


def is_admin(user_id):
    return user_id in ADMIN_IDS


def get_rarity_emoji(rarity):
    return RARITIES.get(rarity, {}).get("emoji", "🟢")


def get_rarity_rating(rarity):
    return RARITIES.get(rarity, {}).get("rating", 10)


# ===== КЛАВИАТУРЫ =====
def main_menu():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
        InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card"),
    )
    markup.add(
        InlineKeyboardButton(text="🏦 Биржа", callback_data="exchange"),
        InlineKeyboardButton(text="🎮 Мини-игры", callback_data="games"),
    )
    markup.add(
        InlineKeyboardButton(text="👤 Профиль", callback_data="profile"),
        InlineKeyboardButton(text="ℹ️ О проекте", callback_data="about"),
    )
    return markup


def back_to_menu():
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"))
    return markup


def games_menu():
    markup = InlineKeyboardMarkup(row_width=1)
    markup.add(
        InlineKeyboardButton(text="🎲 Угадай пилота", callback_data="game_guess_driver"),
        InlineKeyboardButton(text="🗺️ Угадай трассу", callback_data="game_guess_track"),
        InlineKeyboardButton(text="🎲 Бросок кубиков", callback_data="game_dice"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"),
    )
    return markup


def admin_panel():
    markup = InlineKeyboardMarkup(row_width=2)
    markup.add(
        InlineKeyboardButton(text="➕ Добавить карту", callback_data="admin_add"),
        InlineKeyboardButton(text="📝 Редактировать карту", callback_data="admin_edit"),
        InlineKeyboardButton(text="🗑️ Удалить карту", callback_data="admin_delete"),
        InlineKeyboardButton(text="📋 Список карт", callback_data="admin_list"),
        InlineKeyboardButton(text="📊 Статистика", callback_data="admin_stats"),
        InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu"),
    )
    return markup


# ===== ХЕНДЛЕРЫ =====
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


async def callback_handler(call: types.CallbackQuery):
    user_id = call.from_user.id

    if call.data == "back_to_menu":
        await call.message.edit_text("🏁 **Главное меню**", reply_markup=main_menu(), parse_mode="Markdown")
        await call.answer()
        return

    if call.data == "my_cards":
        cards = get_user_cards(user_id)
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
            emoji = get_rarity_emoji(card["rarity"])
            text += f"{emoji} {card['name']} ({code}) ×{qty}\n"
            total += qty
        text += f"\n📊 Всего: {total}"
        await call.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="Markdown")
        await call.answer()
        return

    if call.data == "get_card":
        rarity = random.choices(
            list(RARITIES.keys()),
            weights=[r["chance"] for r in RARITIES.values()],
            k=1
        )[0]
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("SELECT code FROM cards WHERE rarity = ? ORDER BY RANDOM() LIMIT 1", (rarity,))
        row = c.fetchone()
        conn.close()
        if not row:
            await call.answer("❌ Нет карт", show_alert=True)
            return
        code = row[0]
        add_card_to_user(user_id, code, 1)
        card = get_card_info(code)
        emoji = get_rarity_emoji(card["rarity"])
        await call.message.edit_text(
            f"🎲 **Получена карта!**\n\n"
            f"{emoji} {card['name']} ({code})\n"
            f"🏁 {card['team']}\n"
            f"🎴 {card['rarity']}\n"
            f"💰 {card['price']} 💰",
            reply_markup=back_to_menu(),
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data == "exchange":
        user = get_user(user_id)
        cards = get_user_cards(user_id)
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("SELECT code, name, rarity, price FROM cards ORDER BY price DESC LIMIT 15")
        rows = c.fetchall()
        conn.close()
        text = "🏦 **Биржа**\n\n"
        for code, name, rarity, price in rows:
            emoji = get_rarity_emoji(rarity)
            qty = cards.get(code, 0)
            text += f"{emoji} {name} ({code}) — {price} 💰{' (📦x'+str(qty)+')' if qty > 0 else ''}\n"
        text += f"\n💰 Баланс: {user['balance']} 💰\n\n"
        text += "Купить: /buy [код]\n"
        text += "Продать: /sell [код]"
        await call.message.edit_text(text, reply_markup=back_to_menu(), parse_mode="Markdown")
        await call.answer()
        return

    if call.data == "profile":
        user = get_user(user_id)
        cards = get_user_cards(user_id)
        total = sum(cards.values())
        await call.message.edit_text(
            f"👤 **Профиль**\n\n"
            f"Имя: {user['display_name']}\n"
            f"💰 Баланс: {user['balance']} 💰\n"
            f"🎴 Карт: {total}\n"
            f"🏆 Рейтинг: {user['rating']}\n"
            f"🏁 PvP: {user['pvp_wins']}W / {user['pvp_losses']}L\n\n"
            f"/setname — сменить ник",
            reply_markup=back_to_menu(),
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data == "games":
        await call.message.edit_text("🎮 **Мини-игры**", reply_markup=games_menu(), parse_mode="Markdown")
        await call.answer()
        return

    if call.data == "about":
        await call.message.edit_text(
            "ℹ️ **О проекте**\n\n"
            "IndyCard Exchange — карточная игра по IndyCar.\n\n"
            "Разработчики:\n"
            "@Scanialove\n"
            "@Gabriella1488",
            reply_markup=back_to_menu(),
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data.startswith("admin_"):
        if not is_admin(user_id):
            await call.answer("⛔ Нет доступа", show_alert=True)
            return

        if call.data == "admin_add":
            await call.message.edit_text(
                "➕ **Добавление карты**\n\n"
                "Введите данные в формате:\n"
                "`code|name|team|number|rarity|price|year|image`\n\n"
                "Пример:\n"
                "`PAL|Alex Palou|Chip Ganassi|10|LEGENDARY|1200|2026|https://...`\n\n"
                "Фото можно указать позже через редактирование.",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )
            bot.register_next_step_handler(call.message, admin_add_card_step)
            await call.answer()
            return

        if call.data == "admin_edit":
            await call.message.edit_text(
                "📝 **Редактирование карты**\n\n"
                "Введите код карты (например, PAL):",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )
            bot.register_next_step_handler(call.message, admin_edit_select)
            await call.answer()
            return

        if call.data == "admin_list":
            conn = sqlite3.connect("indycard.db")
            c = conn.cursor()
            c.execute("SELECT code, name, rarity, price FROM cards ORDER BY price DESC")
            rows = c.fetchall()
            conn.close()
            text = "📋 **Все карты**\n\n"
            for code, name, rarity, price in rows:
                emoji = get_rarity_emoji(rarity)
                text += f"{emoji} {name} ({code}) — {rarity} — {price} 💰\n"
            await call.message.edit_text(text[:4000], reply_markup=back_to_menu(), parse_mode="Markdown")
            await call.answer()
            return

        if call.data == "admin_stats":
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
                f"📊 **Статистика**\n\n"
                f"👥 Пользователей: {users}\n"
                f"🎴 Всего карт: {cards}\n"
                f"📦 Карт у игроков: {total}",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )
            await call.answer()
            return

        if call.data == "admin_delete":
            await call.message.edit_text(
                "🗑️ **Удаление карты**\n\nВведите код карты:",
                reply_markup=back_to_menu(),
                parse_mode="Markdown",
            )
            bot.register_next_step_handler(call.message, admin_delete_card)
            await call.answer()
            return

    # Мини-игры
    if call.data.startswith("game_"):
        await handle_game(call)
        return

    await call.answer()


# ===== АДМИН-ФУНКЦИИ =====
async def admin_add_card_step(message: types.Message):
    try:
        parts = message.text.split('|')
        if len(parts) < 7:
            await message.answer("❌ Нужно минимум 7 полей: code|name|team|number|rarity|price|year")
            return
        code, name, team, number, rarity, price, year = parts[:7]
        image = parts[7] if len(parts) > 7 else ""

        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("""INSERT INTO cards (code, name, team, number, rarity, price, rating_points, year, image)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (code.upper(), name, team, int(number), rarity, int(price),
             RARITIES.get(rarity, {}).get("rating", 10), int(year), image))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Карта {name} ({code}) добавлена!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


async def admin_edit_select(message: types.Message):
    code = message.text.upper()
    card = get_card_info(code)
    if not card:
        await message.answer("❌ Карта не найдена")
        return
    await message.answer(
        f"✏️ **Редактируем {card['name']} ({code})**\n\n"
        f"Текущие данные:\n"
        f"`{card['name']}|{card['team']}|{card['number']}|{card['rarity']}|{card['price']}|{card['year']}|{card['image'] or 'Нет фото'}`\n\n"
        f"Введите новые данные в том же формате:\n"
        f"`name|team|number|rarity|price|year|image`",
        parse_mode="Markdown"
    )
    bot.register_next_step_handler(message, admin_edit_save, code)


async def admin_edit_save(message: types.Message, code: str):
    try:
        parts = message.text.split('|')
        if len(parts) < 6:
            await message.answer("❌ Нужно минимум 6 полей: name|team|number|rarity|price|year")
            return
        name, team, number, rarity, price, year = parts[:6]
        image = parts[6] if len(parts) > 6 else ""

        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("""UPDATE cards SET name=?, team=?, number=?, rarity=?, price=?, year=?, image=?
            WHERE code=?""", (name, team, int(number), rarity, int(price), int(year), image, code))
        conn.commit()
        conn.close()
        await message.answer(f"✅ Карта {name} ({code}) обновлена!")
    except Exception as e:
        await message.answer(f"❌ Ошибка: {e}")


async def admin_delete_card(message: types.Message):
    code = message.text.upper()
    card = get_card_info(code)
    if not card:
        await message.answer("❌ Карта не найдена")
        return
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("DELETE FROM cards WHERE code = ?", (code,))
    c.execute("DELETE FROM user_cards WHERE code = ?", (code,))
    conn.commit()
    conn.close()
    await message.answer(f"🗑️ Карта {card['name']} ({code}) удалена!")


# ===== МИНИ-ИГРЫ =====
async def handle_game(call: types.CallbackQuery):
    user_id = call.from_user.id

    if call.data == "game_guess_driver":
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("SELECT code, name, team FROM cards ORDER BY RANDOM() LIMIT 1")
        driver = c.fetchone()
        conn.close()
        if not driver:
            await call.answer("❌ Нет пилотов", show_alert=True)
            return
        code, name, team = driver
        conn = sqlite3.connect("indycard.db")
        c = conn.cursor()
        c.execute("SELECT name FROM cards WHERE name != ? ORDER BY RANDOM() LIMIT 3", (name,))
        others = c.fetchall()
        conn.close()
        options = [name] + [o[0] for o in others]
        random.shuffle(options)
        markup = InlineKeyboardMarkup(row_width=2)
        for opt in options:
            markup.add(InlineKeyboardButton(text=opt, callback_data=f"guess_{name}_{opt}"))
        markup.add(InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu"))
        await call.message.edit_text(
            f"🎲 **Угадай пилота**\n\nПодсказка: команда {team}\n\nКто это?",
            reply_markup=markup,
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data == "game_guess_track":
        tracks = [
            {"name": "Indianapolis", "type": "овал"},
            {"name": "Long Beach", "type": "уличная"},
            {"name": "Road America", "type": "шоссе"},
            {"name": "Mid-Ohio", "type": "шоссе"},
            {"name": "Nashville", "type": "уличная"},
            {"name": "Gateway", "type": "овал"}
        ]
        track = random.choice(tracks)
        options = [t["name"] for t in tracks]
        random.shuffle(options)
        markup = InlineKeyboardMarkup(row_width=2)
        for opt in options[:4]:
            markup.add(InlineKeyboardButton(text=opt, callback_data=f"track_{track['name']}_{opt}"))
        markup.add(InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu"))
        await call.message.edit_text(
            f"🗺️ **Угадай трассу**\n\nТип: {track['type']}\n\nКакая это трасса?",
            reply_markup=markup,
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data == "game_dice":
        markup = InlineKeyboardMarkup(row_width=3)
        for i in [10, 25, 50, 100]:
            markup.add(InlineKeyboardButton(text=f"{i} 💰", callback_data=f"dice_bet_{i}"))
        markup.add(InlineKeyboardButton(text="🔙 Отмена", callback_data="back_to_menu"))
        await call.message.edit_text(
            f"🎲 **Бросок кубиков**\n\nВыбери ставку (выигрыш х2 при 6+, х3 при 11+):",
            reply_markup=markup,
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data.startswith("dice_bet_"):
        bet = int(call.data.split("_")[2])
        user = get_user(user_id)
        if user["balance"] < bet:
            await call.answer("❌ Недостаточно средств!", show_alert=True)
            return
        d1, d2 = random.randint(1, 6), random.randint(1, 6)
        total = d1 + d2
        if total >= 11:
            win = bet * 3
        elif total >= 6:
            win = bet * 2
        else:
            win = -bet
        update_balance(user_id, win, "game_dice")
        user = get_user(user_id)
        await call.message.edit_text(
            f"🎲 **Результат**\n\n"
            f"{d1} + {d2} = {total}\n"
            f"{'🎉 Выигрыш: ' + str(win) if win > 0 else '❌ Проигрыш: ' + str(-win)}\n\n"
            f"💰 Баланс: {user['balance']} 💰",
            reply_markup=back_to_menu(),
            parse_mode="Markdown",
        )
        await call.answer()
        return

    if call.data.startswith("guess_") or call.data.startswith("track_"):
        parts = call.data.split("_")
        if call.data.startswith("guess_"):
            correct, answer = parts[1], parts[2]
        else:
            correct, answer = parts[1], parts[2]
        if correct == answer:
            win = 50
            update_balance(user_id, win, "game_guess")
            result = f"✅ Правильно! +{win} 💰"
        else:
            result = f"❌ Неправильно! Это был {correct}"
        user = get_user(user_id)
        await call.message.edit_text(
            f"🎲 **Результат**\n\n{result}\n\n💰 Баланс: {user['balance']} 💰",
            reply_markup=back_to_menu(),
            parse_mode="Markdown",
        )
        await call.answer()
        return


# ===== КОМАНДЫ =====
async def buy_command(message: types.Message):
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
    if user["balance"] < card["price"]:
        await message.answer(f"❌ Нужно {card['price']} 💰")
        return
    update_balance(message.from_user.id, -card["price"], "buy", code)
    add_card_to_user(message.from_user.id, code, 1)
    await message.answer(f"✅ {card['name']} ({code}) куплена за {card['price']} 💰")


async def sell_command(message: types.Message):
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
    price = int(card["price"] * 0.7)
    remove_card_from_user(message.from_user.id, code, 1)
    update_balance(message.from_user.id, price, "sell", code)
    await message.answer(f"✅ {card['name']} ({code}) продана за {price} 💰")


async def balance_command(message: types.Message):
    user = get_user(message.from_user.id)
    await message.answer(f"💰 Твой баланс: {user['balance']} 💰")


async def top_command(message: types.Message):
    conn = sqlite3.connect("indycard.db")
    c = conn.cursor()
    c.execute("SELECT display_name, balance FROM users ORDER BY balance DESC LIMIT 10")
    rows = c.fetchall()
    conn.close()
    text = "🏆 **Топ-10**\n\n"
    for i, (name, balance) in enumerate(rows, 1):
        text += f"{i}. {name} — {balance} 💰\n"
    await message.answer(text, parse_mode="Markdown")


# ===== РЕГИСТРАЦИЯ ХЕНДЛЕРОВ =====
def register_handlers(dp: Dispatcher):
    dp.message.register(start_command, Command("start"))
    dp.message.register(admin_command, Command("admin"))
    dp.message.register(setname_command, Command("setname"))
    dp.message.register(buy_command, Command("buy"))
    dp.message.register(sell_command, Command("sell"))
    dp.message.register(balance_command, Command("balance"))
    dp.message.register(top_command, Command("top"))
    dp.callback_query.register(callback_handler)


# ===== ВЕБХУК =====
async def on_startup(app: web.Application):
    bot = app["bot"]
    await bot.set_webhook(url=f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    logger.info(f"✅ Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")


async def on_shutdown(app: web.Application):
    logger.info("Shutting down...")


def main():
    bot = Bot(token=BOT_TOKEN)
    dp = Dispatcher()
    register_handlers(dp)

    app = web.Application()
    app["bot"] = bot

    # Регистрируем обработчики вебхука
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)

    # Добавляем startup/shutdown хуки
    app.on_startup.append(on_startup)
    app.on_shutdown.append(on_shutdown)

    web.run_app(app, host="0.0.0.0", port=PORT)


if __name__ == "__main__":
    main()
