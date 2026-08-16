import sqlite3
from config import DB_PATH
from data.drivers import DRIVERS
from data.winners import WINNERS
from utils.helpers import RARITIES

def get_db():
    return sqlite3.connect(DB_PATH)

def init_db():
    conn = get_db()
    c = conn.cursor()
    
    c.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            user_id INTEGER PRIMARY KEY,
            username TEXT,
            display_name TEXT,
            balance INTEGER DEFAULT 500,
            rating INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            game_attempts INTEGER DEFAULT 3,
            last_attempt_reset TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            total_cards INTEGER DEFAULT 0,
            credit_rating INTEGER DEFAULT 100,
            total_deposits INTEGER DEFAULT 0,
            total_credits INTEGER DEFAULT 0,
            missed_payments INTEGER DEFAULT 0,
            is_banned_from_bank INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS user_cards (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            code TEXT,
            quantity INTEGER DEFAULT 1,
            acquired_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(user_id, code)
        );
        
        CREATE TABLE IF NOT EXISTS cards (
            code TEXT PRIMARY KEY,
            name TEXT,
            team TEXT,
            number INTEGER,
            rarity TEXT,
            price INTEGER,
            rating_points INTEGER DEFAULT 10,
            year INTEGER,
            image TEXT,
            change_24h REAL DEFAULT 0.0,
            base_price INTEGER DEFAULT 100,
            last_updated TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            season_pos INTEGER DEFAULT 0,
            season_points INTEGER DEFAULT 0,
            update_history TEXT DEFAULT '[]'
        );
        
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            type TEXT,
            code TEXT,
            amount INTEGER,
            balance_after INTEGER,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS deposits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            term INTEGER,
            rate INTEGER,
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_date TIMESTAMP,
            status TEXT DEFAULT 'active',
            interest_earned INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS credits (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            amount INTEGER,
            term INTEGER,
            rate INTEGER,
            start_date TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            end_date TIMESTAMP,
            status TEXT DEFAULT 'active',
            paid_amount INTEGER DEFAULT 0,
            missed_payments INTEGER DEFAULT 0
        );
        
        CREATE TABLE IF NOT EXISTS market_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            card_code TEXT,
            price INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            status TEXT DEFAULT 'active'
        );
        
        CREATE TABLE IF NOT EXISTS pvp_battles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            player1_id INTEGER,
            player2_id INTEGER,
            bet_type TEXT,
            bet_value TEXT,
            status TEXT DEFAULT 'waiting',
            winner_id INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS bank_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id INTEGER,
            action TEXT,
            amount INTEGER,
            details TEXT,
            timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS market_state (
            id INTEGER PRIMARY KEY,
            last_update TIMESTAMP,
            market_data TEXT
        );
        
        CREATE TABLE IF NOT EXISTS promocodes (
            code TEXT PRIMARY KEY,
            reward_type TEXT,
            reward_value TEXT,
            max_uses INTEGER,
            used INTEGER DEFAULT 0,
            created_by INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        
        CREATE TABLE IF NOT EXISTS promo_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT,
            user_id INTEGER,
            used_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            UNIQUE(code, user_id)
        );
        
        CREATE TABLE IF NOT EXISTS race_events (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            date DATE,
            event_name TEXT,
            race_data TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    
    # Заполняем картами
    for code, data in DRIVERS.items():
        c.execute("""
            INSERT OR IGNORE INTO cards 
            (code, name, team, number, rarity, price, rating_points, year, image, base_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code, data["name"], data["team"], data.get("number", 0),
            data["rarity"], data["price"],
            RARITIES.get(data["rarity"], {}).get("rating", 10),
            2026, data.get("image", ""), data["price"]
        ))
    
    for winner in WINNERS:
        code = f"WIN_{winner['driver'][:3].upper()}_{winner['year']}"
        c.execute("""
            INSERT OR IGNORE INTO cards 
            (code, name, team, number, rarity, price, rating_points, year, image, base_price)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            code, winner["driver"], "Indy 500 Winner", 0,
            winner.get("rarity", "INDY_EDITION"), winner.get("price", 500),
            RARITIES.get(winner.get("rarity", "INDY_EDITION"), {}).get("rating", 100),
            winner["year"], "", winner.get("price", 500)
        ))
    
    conn.commit()
    conn.close()
