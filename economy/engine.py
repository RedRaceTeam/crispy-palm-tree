import random
import json
import sqlite3
from datetime import datetime, timedelta
from config import (
    PRICE_CORRECTION_THRESHOLD, 
    MAX_PRICE_CHANGE, 
    MIN_PRICE_CHANGE, 
    MARKET_UPDATE_INTERVAL,
    DB_PATH
)

class MarketEngine:
    """Ядро экономики — динамическая биржа"""
    
    @staticmethod
    def calculate_price_change(card_code: str, current_price: int, rarity: str, base_price: int) -> dict:
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        # 1. Результаты гонок (последние 5)
        c.execute("SELECT race_data FROM race_events ORDER BY date DESC LIMIT 5")
        races = c.fetchall()
        
        race_factor = 0
        for race_data in races:
            data = json.loads(race_data[0])
            if card_code == data.get("winner"):
                race_factor += 25
            elif card_code in data.get("podium", []):
                race_factor += 15
            elif card_code == data.get("pole"):
                race_factor += 10
            elif card_code in data.get("dnf", []):
                race_factor -= 10
        
        # 2. Позиция в чемпионате
        c.execute("SELECT season_pos FROM cards WHERE code = ?", (card_code,))
        row = c.fetchone()
        champ_factor = 0
        if row and row[0]:
            pos = row[0]
            if pos <= 3:
                champ_factor = 15
            elif pos <= 5:
                champ_factor = 10
            elif pos <= 10:
                champ_factor = 5
            elif pos >= 25:
                champ_factor = -10
        
        # 3. Спрос/предложение
        c.execute("SELECT SUM(quantity) FROM user_cards WHERE code = ?", (card_code,))
        supply = c.fetchone()[0] or 0
        
        c.execute("""
            SELECT COUNT(*) FROM transactions 
            WHERE code = ? AND type IN ('market_buy', 'buy')
            AND timestamp > datetime('now', '-7 days')
        """, (card_code,))
        demand = c.fetchone()[0] or 0
        
        c.execute("SELECT COUNT(*) FROM market_listings WHERE card_code = ? AND status = 'active'", (card_code,))
        listings = c.fetchone()[0] or 0
        
        demand_factor = min(15, (demand / max(supply, 1)) * 5) if supply > 0 else 0
        supply_factor = -min(10, supply / 10)
        
        # 4. Редкость
        rarity_bonus = {
            "COMMON": 0,
            "RARE": 2,
            "EPIC": 5,
            "LEGENDARY": 10,
            "INDY_EDITION": 15,
            "ULTIMATE": 20
        }.get(rarity, 0)
        
        # 5. Коррекция цены
        correction = 0
        if base_price and current_price > base_price * PRICE_CORRECTION_THRESHOLD:
            correction = -(current_price - base_price) / base_price * 2
            correction = max(-15, correction)
        
        # 6. Волатильность
        volatility = random.uniform(-3, 3)
        
        total = race_factor + champ_factor + demand_factor + supply_factor + rarity_bonus + correction + volatility
        total = max(MIN_PRICE_CHANGE, min(MAX_PRICE_CHANGE, total))
        
        conn.close()
        
        return {
            "change": total,
            "factors": {
                "race": race_factor,
                "championship": champ_factor,
                "demand": demand_factor,
                "supply": supply_factor,
                "rarity": rarity_bonus,
                "correction": correction,
                "volatility": volatility
            }
        }
    
    @staticmethod
    def update_all_prices():
        conn = sqlite3.connect(DB_PATH)
        c = conn.cursor()
        
        c.execute("SELECT last_update FROM market_state WHERE id = 1")
        row = c.fetchone()
        if row:
            try:
                last = datetime.fromisoformat(row[0])
                if (datetime.now() - last).seconds < MARKET_UPDATE_INTERVAL:
                    conn.close()
                    return {"status": "too_soon"}
            except:
                pass
        
        c.execute("SELECT code, price, rarity, base_price FROM cards")
        cards = c.fetchall()
        
        changes = {}
        for code, price, rarity, base in cards:
            result = MarketEngine.calculate_price_change(code, price, rarity, base)
            change = result["change"]
            new_price = int(price * (1 + change / 100))
            new_price = max(10, new_price)
            
            c.execute("""
                UPDATE cards SET price = ?, change_24h = ?, last_updated = CURRENT_TIMESTAMP
                WHERE code = ?
            """, (new_price, round(change, 1), code))
            
            changes[code] = {"old": price, "new": new_price, "change": round(change, 1)}
        
        c.execute("""
            INSERT OR REPLACE INTO market_state (id, last_update, market_data)
            VALUES (1, ?, ?)
        """, (datetime.now().isoformat(), json.dumps(changes)))
        
        conn.commit()
        conn.close()
        return {"status": "success", "changes": changes}
