import asyncio
import logging
from economy.engine import MarketEngine

logger = logging.getLogger(__name__)

class MarketScheduler:
    @staticmethod
    async def start():
        logger.info("📈 Биржа запущена")
        await MarketScheduler._update()
        while True:
            await asyncio.sleep(1800)
            await MarketScheduler._update()
    
    @staticmethod
    async def _update():
        try:
            result = MarketEngine.update_all_prices()
            if result["status"] == "success":
                logger.info(f"✅ Цены обновлены: {len(result['changes'])} карт")
        except Exception as e:
            logger.error(f"❌ Ошибка обновления цен: {e}")
