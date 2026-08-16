from aiogram import Router, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery

from database.queries import create_user, get_user
from keyboards.inline import main_menu, back_button
from utils.helpers import get_attempts_display

router = Router()

@router.message(Command("start"))
async def cmd_start(message: Message):
    create_user(message.from_user.id, message.from_user.username)
    user = get_user(message.from_user.id)
    
    await message.answer(
        f"🏁 **IndyCard Exchange**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(message.from_user.id)}\n\n"
        f"Выбирай действие:",
        reply_markup=main_menu(message.from_user.id),
        parse_mode="Markdown"
    )

@router.callback_query(F.data == "back_to_menu")
async def cb_back_to_menu(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    
    await callback.message.edit_text(
        f"🏁 **Главное меню**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(callback.from_user.id)}",
        reply_markup=main_menu(callback.from_user.id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "about")
async def cb_about(callback: CallbackQuery):
    await callback.message.edit_text(
        "ℹ️ **IndyCard Exchange**\n\n"
        "Карточная игра по мотивам IndyCar.\n\n"
        "🎴 Собирай карты пилотов и легенд\n"
        "🏦 Банк с депозитами и кредитами\n"
        "🎲 Попытки для получения карт\n\n"
        "Разработчики: @Scanialove, @Gabriella1488",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "profile")
async def cb_profile(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    cards = get_user_cards(callback.from_user.id)
    
    await callback.message.edit_text(
        f"👤 **Профиль**\n\n"
        f"👤 Имя: {user['username'] or user['display_name']}\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(callback.from_user.id)}\n"
        f"🎴 Всего карт: {user['total_cards']}\n"
        f"📦 Уникальных: {len(cards)}\n"
        f"🏆 Рейтинг: {user['rating']}",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "shop")
async def cb_shop(callback: CallbackQuery):
    user = get_user(callback.from_user.id)
    
    await callback.message.edit_text(
        f"🏪 **Магазин**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(callback.from_user.id)}\n\n"
        f"Выбери, что хочешь купить:",
        reply_markup=shop_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "buy_attempt_1")
async def cb_buy_attempt_1(callback: CallbackQuery):
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
async def cb_buy_attempt_3(callback: CallbackQuery):
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
