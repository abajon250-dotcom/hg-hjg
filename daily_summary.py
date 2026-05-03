from datetime import datetime, timedelta
from db import get_pool

async def send_daily_summary(bot):
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch("SELECT user_id FROM users")
        for row in rows:
            user_id = row['user_id']
            # за сегодня
            stats_today = await conn.fetchrow("""
                SELECT COUNT(*) as accepted, COALESCE(SUM(earned_amount), 0) as earned,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='block' THEN 1 END) as blocked,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='noscan' THEN 1 END) as noscan
                FROM qr_submissions
                WHERE user_id = $1 AND status = 'accepted' AND DATE(submitted_at) = $2
            """, user_id, today)
            stats_yest = await conn.fetchrow("""
                SELECT COUNT(*) as accepted, COALESCE(SUM(earned_amount), 0) as earned,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='block' THEN 1 END) as blocked,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='noscan' THEN 1 END) as noscan
                FROM qr_submissions
                WHERE user_id = $1 AND status = 'accepted' AND DATE(submitted_at) = $2
            """, user_id, yesterday)
            text = f"📊 **Итоги дня {yesterday}**\n\n"
            if stats_yest['accepted'] == 0:
                text += "За вчерашний день не было зачтённых номеров.\n"
            else:
                text += f"✅ Принято номеров: {stats_yest['accepted']}\n"
                text += f"💰 Заработано: {stats_yest['earned']:.2f}$\n"
                text += f"🚫 Блоки: {stats_yest['blocked']}\n"
                text += f"📸 Несканы: {stats_yest['noscan']}\n"
            text += f"\n📈 **Сегодня (уже сдано и зачтено):**\n"
            text += f"✅ {stats_today['accepted']}\n💰 {stats_today['earned']:.2f}$\n"
            try:
                await bot.send_message(user_id, text, parse_mode="Markdown")
            except:
                pass