# bot.py — IndyCard Бот (точка входа)

import asyncio
import logging
from aiohttp import web
from aiogram import Bot, Dispatcher
from aiogram.webhook.aiohttp_server import SimpleRequestHandler, setup_application

from config import BOT_TOKEN, WEBHOOK_URL, WEBHOOK_PATH, PORT
from database.db import init_db
from handlers.common import router as common_router
from handlers.collection import router as collection_router
from handlers.bank import router as bank_router
from economy.market import MarketScheduler

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

bot = Bot(token=BOT_TOKEN)
dp = Dispatcher()

# Подключаем роутеры
dp.include_router(common_router)
dp.include_router(collection_router)
dp.include_router(bank_router)

async def on_startup():
    await bot.set_webhook(f"{WEBHOOK_URL}{WEBHOOK_PATH}")
    logger.info(f"✅ Вебхук установлен: {WEBHOOK_URL}{WEBHOOK_PATH}")
    asyncio.create_task(MarketScheduler.start())

async def on_shutdown():
    await bot.delete_webhook()
    logger.info("❌ Вебхук удалён")

def main():
    init_db()
    
    if WEBHOOK_URL:
        logger.info(f"🚀 Запуск в режиме вебхука на порту {PORT}")
        app = web.Application()
        SimpleRequestHandler(dispatcher=dp, bot=bot).register(app, path=WEBHOOK_PATH)
        setup_application(app, dp, bot=bot)
        web.run_app(app, host="0.0.0.0", port=PORT)
    else:
        logger.info("🚀 Запуск в режиме поллинга")
        dp.run_polling(bot)

if __name__ == "__main__":
    main()
