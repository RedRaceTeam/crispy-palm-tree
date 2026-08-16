from aiogram import Router, F
from aiogram.types import CallbackQuery, Message
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup

from filters.callback_data import BankCallback
from database.queries import get_user, update_balance, get_credit_rating, get_credit_level
from keyboards.inline import bank_menu, deposit_menu, credit_menu, back_button, credit_rating_guide
from utils.helpers import get_attempts_display

router = Router()

# ============================================================
# FSM СОСТОЯНИЯ
# ============================================================

class BankStates(StatesGroup):
    waiting_deposit_amount = State()
    waiting_credit_amount = State()

# ============================================================
# БАНК — ГЛАВНОЕ МЕНЮ
# ============================================================

@router.callback_query(F.data == "bank_menu")
async def cb_bank_menu(callback: CallbackQuery):
    user_id = callback.from_user.id
    user = get_user(user_id)
    
    await callback.message.edit_text(
        f"🏦 **Банк IndyCard**\n\n"
        f"💰 Баланс: {user['balance']} 💰\n"
        f"🎲 Попытки: {get_attempts_display(user_id)}\n\n"
        f"Выберите действие:",
        reply_markup=bank_menu(user_id),
        parse_mode="Markdown"
    )
    await callback.answer()

# ============================================================
# ДЕПОЗИТЫ
# ============================================================

@router.callback_query(F.data == "bank_deposits")
async def cb_bank_deposits(callback: CallbackQuery):
    await callback.message.edit_text(
        "💰 **Депозиты**\n\n"
        "📅 7 дней — 5% (мин 100 💰)\n"
        "📅 30 дней — 12% (мин 500 💰)\n"
        "📅 90 дней — 25% (мин 1000 💰)\n\n"
        "Выберите срок:",
        reply_markup=deposit_menu(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(BankCallback.filter(F.action == "deposit"))
async def cb_deposit_create(callback: CallbackQuery, callback_data: BankCallback, state: FSMContext):
    term = callback_data.term
    rates = {7: {"rate": 5, "min": 100, "max": 10000}, 
             30: {"rate": 12, "min": 500, "max": 50000},
             90: {"rate": 25, "min": 1000, "max": 100000}}
    rate_data = rates[term]
    
    await state.update_data(term=term)
    await state.set_state(BankStates.waiting_deposit_amount)
    
    await callback.message.edit_text(
        f"💰 **Открытие депозита**\n\n"
        f"📅 Срок: {term} дней\n"
        f"📈 Ставка: {rate_data['rate']}%\n"
        f"💳 Мин: {rate_data['min']} 💰 | Макс: {rate_data['max']} 💰\n\n"
        f"Введите сумму:",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(BankStates.waiting_deposit_amount)
async def process_deposit_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Введите положительное число")
            return
        
        data = await state.get_data()
        term = data["term"]
        rates = {7: {"rate": 5}, 30: {"rate": 12}, 90: {"rate": 25}}
        rate = rates[term]["rate"]
        
        update_balance(message.from_user.id, -amount, "deposit")
        user = get_user(message.from_user.id)
        
        await message.answer(
            f"✅ **Депозит открыт!**\n\n"
            f"💰 Сумма: {amount} 💰\n"
            f"📅 Срок: {term} дней\n"
            f"📈 Ставка: {rate}%\n"
            f"💵 Прибыль: {int(amount * rate / 100)} 💰\n\n"
            f"💰 Новый баланс: {user['balance']} 💰",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Введите число")
    
    await state.clear()

# ============================================================
# КРЕДИТЫ
# ============================================================

@router.callback_query(F.data == "bank_credits")
async def cb_bank_credits(callback: CallbackQuery):
    user_id = callback.from_user.id
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    if level["max_credit"] == 0:
        await callback.message.edit_text(
            "❌ **Кредиты недоступны!**\n\n"
            "Ваш кредитный рейтинг слишком низкий.\n\n"
            "📊 **Как повысить:**\n"
            "• Открывайте депозиты\n"
            "• Вовремя погашайте кредиты\n"
            "• Не допускайте просрочек",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
        await callback.answer()
        return
    
    await callback.message.edit_text(
        f"💳 **Кредиты**\n\n"
        f"📊 Рейтинг: {level['emoji']} {level['name']}\n"
        f"🏦 Лимит: {level['max_credit']} 💰\n\n"
        f"📅 3 дня — 10%\n"
        f"📅 7 дней — 15%\n"
        f"📅 30 дней — 20%\n\n"
        f"Выберите срок:",
        reply_markup=credit_menu(user_id),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(BankCallback.filter(F.action == "credit"))
async def cb_credit_create(callback: CallbackQuery, callback_data: BankCallback, state: FSMContext):
    term = callback_data.term
    user_id = callback.from_user.id
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    if level["max_credit"] == 0:
        await callback.answer("❌ Кредиты недоступны!", show_alert=True)
        return
    
    rates = {3: {"rate": 10}, 7: {"rate": 15}, 30: {"rate": 20}}
    rate = rates[term]["rate"] + level["rate_bonus"]
    
    await state.update_data(term=term, rate=rate)
    await state.set_state(BankStates.waiting_credit_amount)
    
    await callback.message.edit_text(
        f"💳 **Оформление кредита**\n\n"
        f"📅 Срок: {term} дней\n"
        f"📈 Ставка: {rate}%\n"
        f"🏦 Лимит: {level['max_credit']} 💰\n\n"
        f"Введите сумму:",
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.message(BankStates.waiting_credit_amount)
async def process_credit_amount(message: Message, state: FSMContext):
    try:
        amount = int(message.text.strip())
        if amount <= 0:
            await message.answer("❌ Введите положительное число")
            return
        
        data = await state.get_data()
        term = data["term"]
        rate = data["rate"]
        user_id = message.from_user.id
        
        rating = get_credit_rating(user_id)
        level = get_credit_level(rating)
        if amount > level["max_credit"]:
            await message.answer(f"❌ Превышен лимит! Максимум {level['max_credit']} 💰")
            return
        
        update_balance(user_id, amount, "credit")
        user = get_user(user_id)
        
        await message.answer(
            f"✅ **Кредит одобрен!**\n\n"
            f"💰 Сумма: {amount} 💰\n"
            f"📅 Срок: {term} дней\n"
            f"📈 Ставка: {rate}%\n"
            f"💳 К возврату: {int(amount * (1 + rate / 100))} 💰\n\n"
            f"💰 Новый баланс: {user['balance']} 💰\n\n"
            f"⚠️ При просрочке банк изымает карты!",
            reply_markup=back_button(),
            parse_mode="Markdown"
        )
    except ValueError:
        await message.answer("❌ Введите число")
    
    await state.clear()

# ============================================================
# КРЕДИТНЫЙ РЕЙТИНГ
# ============================================================

@router.callback_query(F.data == "bank_rating")
async def cb_bank_rating(callback: CallbackQuery):
    user_id = callback.from_user.id
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    text = f"📊 **Кредитный рейтинг**\n\n"
    text += f"Текущий рейтинг: {level['emoji']} {level['name']}\n"
    text += f"Значение: {rating}/100\n"
    text += f"Кредитный лимит: {level['max_credit']} 💰\n"
    text += f"Бонус к ставке: +{level['rate_bonus']}%\n\n"
    
    text += "📋 **Уровни рейтинга:**\n"
    for threshold in sorted([80, 60, 40, 20, 0], reverse=True):
        lvl = get_credit_level(threshold)
        if rating >= threshold:
            text += f"✅ {lvl['emoji']} {lvl['name']} ({threshold}+) — ваш уровень\n"
        else:
            text += f"⬜ {lvl['emoji']} {lvl['name']} ({threshold}+)\n"
    
    text += "\n📌 **Как повысить рейтинг:**\n"
    text += "✅ Открывайте депозиты и не снимайте досрочно\n"
    text += "✅ Вовремя погашайте кредиты\n"
    text += "✅ Не допускайте просрочек"
    
    await callback.message.edit_text(
        text,
        reply_markup=back_button(),
        parse_mode="Markdown"
    )
    await callback.answer()

@router.callback_query(F.data == "bank_rating_guide")
async def cb_bank_rating_guide(callback: CallbackQuery):
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
    text += "   • Просрочка >14 дней: арест счёта"
    
    await callback.message.edit_text(
        text,
        reply_markup=credit_rating_guide(),
        parse_mode="Markdown"
    )
    await callback.answer()
