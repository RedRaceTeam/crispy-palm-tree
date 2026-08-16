import random
import sqlite3
from aiogram import Router, F
from aiogram.types import CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from filters.callback_data import CardCallback
from database.queries import (
    get_user, get_user_cards, get_card_info, add_card_to_user,
    get_game_attempts, use_attempt, add_attempt, update_balance
)
from keyboards.inline import back_button, collection_menu
from utils.helpers import get_rarity_emoji, get_rarity_name, get_rarity_icon, get_attempts_display, RARITIES
from config import DB_PATH

router = Router()
user_carousel = {}

# ============================================================
# КОЛЛЕКЦИЯ
# ============================================================

@router.callback_query(F.data == "collection")
async def cb_collection(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    
    await callback.message.edit_text(
        f"🎴 **Коллекция**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(callback.from_user.id)}\n\n"
        f"Здесь ты можешь посмотреть свои карты\n"
        f"и получить новые!",
        reply_markup=collection_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# КАРУСЕЛЬ
# ============================================================

@router.callback_query(F.data == "my_cards")
async def cb_my_cards(callback: CallbackQuery):
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
    
    # Сортировка по редкости
    rarity_order = {"ULTIMATE": 0, "INDY_EDITION": 1, "LEGENDARY": 2, 
                    "EPIC": 3, "RARE": 4, "COMMON": 5}
    
    card_codes = list(cards.keys())
    card_codes.sort(key=lambda x: rarity_order.get(get_card_info(x)["rarity"], 99))
    
    user_carousel[user_id] = {"cards": card_codes, "index": 0}
    await show_card(callback.message, user_id, 0, callback)

async def show_card(message, user_id: int, index: int, callback=None):
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
            callback_data=CardCallback(action="prev", code=cards[prev_idx], index=prev_idx).pack()
        )
        builder.button(
            text=f"{index+1}/{total}",
            callback_data=CardCallback(action="view", code=code, index=index).pack()
        )
        builder.button(
            text="▶️",
            callback_data=CardCallback(action="next", code=cards[next_idx], index=next_idx).pack()
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
    except Exception:
        await message.edit_text(
            f"{icon} **{card['name']}**\n\n" + text,
            reply_markup=builder.as_markup(),
            parse_mode="Markdown"
        )
    
    if callback:
        await callback.answer()

# ============================================================
# НАВИГАЦИЯ КАРУСЕЛИ
# ============================================================

@router.callback_query(CardCallback.filter())
async def cb_carousel(callback: CallbackQuery, callback_data: CardCallback):
    user_id = callback.from_user.id
    
    data = user_carousel.get(user_id)
    if not data:
        await callback.answer("❌ Сессия истекла")
        return
    
    cards = data["cards"]
    if not cards:
        await callback.answer("❌ Нет карт")
        return
    
    action = callback_data.action
    
    if action in ("prev", "next"):
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
async def cb_get_card(callback: CallbackQuery):
    user_id = callback.from_user.id
    
    if not use_attempt(user_id):
        await callback.answer("❌ Нет попыток! Купи в магазине или подожди", show_alert=True)
        return
    
    rarities = []
    for r, d in RARITIES.items():
        rarities.extend([r] * d["chance"])
    rarity = random.choice(rarities)
    
    conn = sqlite3.connect(DB_PATH)
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
