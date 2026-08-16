# filters/callback_data.py
from aiogram.filters.callback_data import CallbackData
from typing import Optional

class CardCallback(CallbackData, prefix="card"):
    """Callback для карт и карусели"""
    action: str  # prev, next, view
    code: str = ""
    index: int = 0

class BankCallback(CallbackData, prefix="bank"):
    """Callback для банка"""
    action: str  # deposit, credit, repay
    amount: int = 0
    term: int = 0
    credit_id: int = 0

class MarketCallback(CallbackData, prefix="market"):
    """Callback для рынка"""
    action: str  # buy, sell, list
    listing_id: int = 0
    card_code: str = ""

class AdminCallback(CallbackData, prefix="admin"):
    """Callback для админки"""
    action: str  # ban, warn, kick, promo
    user_id: int = 0
    card_code: str = ""
