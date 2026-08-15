import os
import logging
import sqlite3
import random
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application
from aiohttp import web

# ===== НАСТРОЙКИ =====
BOT_TOKEN = os.getenv("BOT_TOKEN")
WEBHOOK_URL = os.getenv("WEBHOOK_URL")
WEBHOOK_PATH = "/webhook"
PORT = int(os.getenv("PORT", 8000))

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ===== КЛАВИАТУРЫ =====
def main_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎴 Мои карты", callback_data="my_cards"),
         InlineKeyboardButton(text="🎲 Получить карту", callback_data="get_card")]
    ])

def back_to_menu():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_data="back_to_menu")]
    ])

# ===== БОТ И ДИСПЕТЧЕР =====
bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# ===== ХЕНДЛЕРЫ =====
@dp.message(Command("start"))
async def start(message: Message):
    await message.answer(
        "🏁 **IndyCard Exchange**\n\nДобро пожаловать!",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )

@dp.callback_query(F.data == "back_to_menu")
async def back_to_menu_callback(call: CallbackQuery):
    await call.message.edit_text(
        "🏁 **Главное меню**",
        reply_markup=main_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "my_cards")
async def my_cards(call: CallbackQuery):
    await call.message.edit_text(
        "🎴 **Мои карты**\n\nПока пусто",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

@dp.callback_query(F.data == "get_card")
async def get_card(call: CallbackQuery):
    # Заглушка — позже добавишь свою логику
    await call.message.edit_text(
        "🎲 **Получена карта!**\n\nAlex Palou (LEGENDARY)",
        reply_markup=back_to_menu(),
        parse_mode="Markdown"
    )
    await call.answer()

# ===== ВЕБХУК С ПРАВИЛЬНЫМИ allowed_updates =====
async def on_startup(app: web.Application):
    await bot.set_webhook(
        url=f"{WEBHOOK_URL}{WEBHOOK_PATH}",
        allowed_updates=["message", "callback_query"]  # <-- ГЛАВНОЕ!
    )
    logger.info(f"✅ Webhook set to {WEBHOOK_URL}{WEBHOOK_PATH}")

def main():
    app = web.Application()
    app["bot"] = bot
    SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
    setup_application(app, dp, bot=bot)
    app.on_startup.append(on_startup)
    web.run_app(app, host="0.0.0.0", port=PORT)

if __name__ == "__main__":
    main()
