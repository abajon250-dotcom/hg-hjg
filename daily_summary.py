import aiosqlite
from datetime import datetime, timedelta
from db import DATABASE

async def send_daily_summary(bot):
    """Отправляет каждому пользователю итоги за день в 18:00 МСК"""
    today = datetime.now().date().isoformat()
    yesterday = (datetime.now() - timedelta(days=1)).date().isoformat()
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        # Получаем всех пользователей
        users = await db.execute("SELECT user_id FROM users")
        rows = await users.fetchall()
        for row in rows:
            user_id = row['user_id']
            # Статистика за сегодня (принятые заявки)
            cur = await db.execute("""
                SELECT COUNT(*) as accepted,
                       COALESCE(SUM(earned_amount), 0) as earned,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='block' THEN 1 END) as blocked,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='noscan' THEN 1 END) as noscan
                FROM qr_submissions
                WHERE user_id = ? AND status = 'accepted' AND DATE(submitted_at) = ?
            """, (user_id, today))
            stats_today = await cur.fetchone()
            # Статистика за вчера (отправляем итоги за вчерашний день)
            cur2 = await db.execute("""
                SELECT COUNT(*) as accepted,
                       COALESCE(SUM(earned_amount), 0) as earned,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='block' THEN 1 END) as blocked,
                       COUNT(CASE WHEN status='rejected' AND reject_reason='noscan' THEN 1 END) as noscan
                FROM qr_submissions
                WHERE user_id = ? AND status = 'accepted' AND DATE(submitted_at) = ?
            """, (user_id, yesterday))
            stats_yesterday = await cur2.fetchone()

            text = f"📊 **Итоги дня {yesterday}**\n\n"
            if stats_yesterday['accepted'] == 0:
                text += "За вчерашний день не было зачтённых номеров.\n"
            else:
                text += f"✅ Принято номеров: {stats_yesterday['accepted']}\n"
                text += f"💰 Заработано: {stats_yesterday['earned']:.2f}$\n"
                text += f"🚫 Блоки: {stats_yesterday['blocked']}\n"
                text += f"📸 Несканы: {stats_yesterday['noscan']}\n"
            text += f"\n📈 **Сегодня (уже сдано и зачтено):**\n"
            text += f"✅ {stats_today['accepted']}\n💰 {stats_today['earned']:.2f}$\n"
            try:
                await bot.send_message(user_id, text, parse_mode="Markdown")
            except:
                pass