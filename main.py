import asyncio
import logging
from aiogram import Bot, Dispatcher
from aiogram.enums import ParseMode
from aiogram.client.default import DefaultBotProperties
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from datetime import datetime

from config import BOT_TOKEN
from db import init_db_pool, init_db, get_hold_submissions, get_pool
from utils import calculate_rank
import user_handlers
import admin_handlers
import callback_handlers
from middleware import SubscriptionMiddleware
from callback_handlers import start_hold_timer
from daily_summary import send_daily_summary

# Функция для сброса ежедневных выплат (обнуление earned_today)
async def reset_daily_earnings():
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute("UPDATE users SET earned_today = 0")
        print("Daily earnings reset")

async def schedule_daily_summary(bot: Bot):
    scheduler = AsyncIOScheduler(timezone="Europe/Moscow")
    # Отправка итогов в 18:00
    scheduler.add_job(send_daily_summary, "cron", hour=18, minute=0, args=[bot])
    # Сброс earned_today в 00:00
    scheduler.add_job(reset_daily_earnings, "cron", hour=0, minute=0)
    scheduler.start()

async def restore_holds(bot: Bot):
    submissions = await get_hold_submissions()
    for sub in submissions:
        hold_until = sub['hold_until']
        delay = (hold_until - datetime.now()).total_seconds()
        if delay > 0:
            asyncio.create_task(start_hold_timer(bot, sub['id'], sub['price'], sub['user_id'], delay))

async def main():
    logging.basicConfig(level=logging.INFO)
    bot = Bot(token=BOT_TOKEN, default=DefaultBotProperties(parse_mode=ParseMode.HTML))
    dp = Dispatcher()

    await init_db_pool()
    await init_db()

    dp.message.middleware(SubscriptionMiddleware())
    dp.callback_query.middleware(SubscriptionMiddleware())

    dp.include_router(user_handlers.router)
    dp.include_router(admin_handlers.router)
    dp.include_router(callback_handlers.router)

    # Запуск планировщика
    await schedule_daily_summary(bot)

    await bot.delete_webhook(drop_pending_updates=True)
    await restore_holds(bot)
    await dp.start_polling(bot)

if __name__ == "__main__":
    asyncio.run(main())