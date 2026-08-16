from aiogram.types import InlineKeyboardMarkup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from filters.callback_data import BankCallback
from database.queries import get_credit_rating, get_credit_level

# ============================================================
# ГЛАВНОЕ МЕНЮ
# ============================================================

def main_menu(user_id: int = None) -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎴 Коллекция", callback_data="collection")
    builder.button(text="🏦 Банк", callback_data="bank_menu")
    builder.button(text="👤 Профиль", callback_data="profile")
    builder.button(text="🏪 Магазин", callback_data="shop")
    builder.button(text="ℹ️ О проекте", callback_data="about")
    builder.adjust(2, 2, 1)
    return builder.as_markup()

def back_button() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(1)
    return builder.as_markup()

# ============================================================
# БАНК
# ============================================================

def bank_menu(user_id: int) -> InlineKeyboardMarkup:
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="💰 Депозиты", callback_data="bank_deposits")
    builder.button(text="💳 Кредиты", callback_data="bank_credits")
    builder.button(text=f"📊 Рейтинг: {level['emoji']}", callback_data="bank_rating")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def deposit_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📅 7 дней (5%)", callback_data=BankCallback(action="deposit", term=7).pack())
    builder.button(text="📅 30 дней (12%)", callback_data=BankCallback(action="deposit", term=30).pack())
    builder.button(text="📅 90 дней (25%)", callback_data=BankCallback(action="deposit", term=90).pack())
    builder.button(text="🔙 Назад", callback_data="bank_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def credit_menu(user_id: int) -> InlineKeyboardMarkup:
    rating = get_credit_rating(user_id)
    level = get_credit_level(rating)
    
    builder = InlineKeyboardBuilder()
    
    if level["max_credit"] > 0:
        builder.button(text="📅 3 дня (10%)", callback_data=BankCallback(action="credit", term=3).pack())
        builder.button(text="📅 7 дней (15%)", callback_data=BankCallback(action="credit", term=7).pack())
        builder.button(text="📅 30 дней (20%)", callback_data=BankCallback(action="credit", term=30).pack())
    else:
        builder.button(text="❌ Кредиты недоступны", callback_data="bank_rating_guide")
    
    builder.button(text="🔙 Назад", callback_data="bank_menu")
    builder.adjust(2, 1, 1)
    return builder.as_markup()

def credit_rating_guide() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="✅ Я понял", callback_data="bank_menu")
    builder.adjust(1)
    return builder.as_markup()

# ============================================================
# КОЛЛЕКЦИЯ
# ============================================================

def collection_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="📋 Мои карты", callback_data="my_cards")
    builder.button(text="🎲 Получить карту", callback_data="get_card")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)
    return builder.as_markup()

# ============================================================
# МАГАЗИН
# ============================================================

def shop_menu() -> InlineKeyboardMarkup:
    builder = InlineKeyboardBuilder()
    builder.button(text="🎲 Попытка +1 (50 💰)", callback_data="buy_attempt_1")
    builder.button(text="🎲 Попытка +3 (120 💰)", callback_data="buy_attempt_3")
    builder.button(text="🔙 Назад", callback_data="back_to_menu")
    builder.adjust(2, 1)
    return builder.as_markup()
