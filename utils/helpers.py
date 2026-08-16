from database.queries import get_game_attempts

# ============================================================
# РЕДКОСТИ
# ============================================================

RARITIES = {
    "COMMON": {"emoji": "🟢", "rating": 10, "chance": 50, "name": "Common", "color": "#4CAF50", "icon": "📄"},
    "RARE": {"emoji": "🔵", "rating": 25, "chance": 25, "name": "Rare", "color": "#2196F3", "icon": "⭐"},
    "EPIC": {"emoji": "🟣", "rating": 40, "chance": 15, "name": "Epic", "color": "#9C27B0", "icon": "🔮"},
    "LEGENDARY": {"emoji": "🟡", "rating": 60, "chance": 7, "name": "Legendary", "color": "#FFD700", "icon": "👑"},
    "INDY_EDITION": {"emoji": "🔴", "rating": 100, "chance": 2, "name": "Indy Edition", "color": "#E53935", "icon": "🏆"},
    "ULTIMATE": {"emoji": "💎", "rating": 150, "chance": 1, "name": "Ultimate", "color": "#FF6B35", "icon": "🌟"},
}

def get_rarity_emoji(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("emoji", "🟢")

def get_rarity_name(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("name", "Common")

def get_rarity_icon(rarity: str) -> str:
    return RARITIES.get(rarity, {}).get("icon", "📄")

def get_attempts_display(user_id: int) -> str:
    attempts = get_game_attempts(user_id)
    full = "🎲" * attempts
    empty = "⬜" * (3 - attempts)
    return f"{full}{empty}"

def format_balance(balance: int) -> str:
    return f"{balance:,}".replace(",", " ")

def format_price(price: int) -> str:
    if price >= 1000000:
        return f"{price // 1000000}M 💰"
    elif price >= 1000:
        return f"{price // 1000}K 💰"
    return f"{price} 💰"
