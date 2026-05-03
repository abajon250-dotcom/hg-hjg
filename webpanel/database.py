from db import get_pool
from typing import List, Dict

async def fetch(query: str, *args) -> List[Dict]:
    pool = await get_pool()
    async with pool.acquire() as conn:
        rows = await conn.fetch(query, *args)
        return [dict(row) for row in rows]

async def execute(query: str, *args):
    pool = await get_pool()
    async with pool.acquire() as conn:
        await conn.execute(query, *args)

async def get_dashboard_stats():
    res = await fetch("""
        SELECT
            (SELECT COUNT(*) FROM users) AS total_users,
            (SELECT COUNT(*) FROM qr_submissions WHERE DATE(submitted_at) = CURRENT_DATE) AS submissions_today,
            (SELECT COALESCE(SUM(earned_amount),0) FROM qr_submissions WHERE status='accepted' AND DATE(submitted_at) = CURRENT_DATE) AS earned_today,
            (SELECT COUNT(*) FROM withdraw_requests WHERE status='pending') AS pending_withdrawals
    """)
    return res[0] if res else {}

async def get_recent_submissions(limit=10):
    return await fetch("SELECT id, user_id, operator, price, phone, status, submitted_at FROM qr_submissions ORDER BY submitted_at DESC LIMIT $1", limit)

async def get_all_users():
    return await fetch("SELECT user_id, username, total_earned, earned_today, role FROM users ORDER BY user_id LIMIT 200")

async def get_submissions_ratio():
    r = await fetch("""
        SELECT 
            COUNT(CASE WHEN status='accepted' THEN 1 END) as accepted,
            COUNT(CASE WHEN status='rejected' THEN 1 END) as rejected,
            COUNT(CASE WHEN status NOT IN ('accepted','rejected') THEN 1 END) as pending
        FROM qr_submissions
    """)
    if r:
        total = r[0]['accepted'] + r[0]['rejected'] + r[0]['pending']
        if total:
            r[0]['accepted_pct'] = round(r[0]['accepted']/total*100)
            r[0]['rejected_pct'] = round(r[0]['rejected']/total*100)
            r[0]['pending_pct'] = 100 - r[0]['accepted_pct'] - r[0]['rejected_pct']
        else:
            r[0]['accepted_pct'] = r[0]['rejected_pct'] = r[0]['pending_pct'] = 0
        return r[0]
    return {"accepted":0,"rejected":0,"pending":0}

async def get_recent_notifications():
    # Простая имитация — можно заменить на реальные события
    return [
        {"text": "Новая заявка от @user123: 2 мин назад", "type": "info"},
        {"text": "Новый тикет от @user456: 5 мин назад", "type": "warning"},
    ]

async def get_open_tickets():
    return await fetch("SELECT id, user_id, category, message, created_at FROM tickets WHERE status = 'open' ORDER BY created_at ASC")

async def answer_ticket(ticket_id: int, response: str, admin_id: int):
    ticket = await fetch("SELECT user_id FROM tickets WHERE id = $1", ticket_id)
    if not ticket:
        return None
    user_id = ticket[0]['user_id']
    await execute("UPDATE tickets SET admin_response = $1, status = 'closed', updated_at = NOW(), closed_at = NOW() WHERE id = $2", response, ticket_id)
    return user_id

async def get_blacklist():
    return await fetch("SELECT phone, created_at FROM blacklist ORDER BY created_at DESC")

async def add_to_blacklist(phone: str, admin_id: int):
    await execute("INSERT INTO blacklist (phone, created_at, admin_id) VALUES ($1, NOW(), $2) ON CONFLICT (phone) DO NOTHING", phone, admin_id)

async def remove_from_blacklist(phone: str):
    await execute("DELETE FROM blacklist WHERE phone = $1", phone)

async def get_operators():
    return await fetch("SELECT * FROM operators ORDER BY name")

async def update_operator_price(operator: str, price_hold: float, price_bh: float):
    await execute("UPDATE operators SET price_hold = $1, price_bh = $2 WHERE name = $3", price_hold, price_bh, operator)

async def update_operator_slot(operator: str, slot_limit: int):
    await execute("UPDATE operators SET slot_limit = $1 WHERE name = $2", slot_limit, operator)

async def get_custom_texts():
    return await fetch("SELECT key, value, updated_at FROM custom_texts")

async def set_custom_text(key: str, value: str):
    await execute("INSERT INTO custom_texts (key, value, updated_at) VALUES ($1, $2, NOW()) ON CONFLICT (key) DO UPDATE SET value = $2, updated_at = NOW()", key, value)

async def get_workers():
    return await fetch("SELECT user_id, username, permissions FROM users WHERE role = 'worker'")

async def add_worker(user_id: int, permissions: str = ""):
    from db import add_worker as db_add_worker
    await db_add_worker(user_id, permissions)

async def remove_worker(user_id: int):
    from db import remove_worker as db_remove_worker
    await db_remove_worker(user_id)

async def get_api_keys():
    return await fetch("SELECT id, user_id, api_key, permissions, created_at, last_used FROM api_keys ORDER BY created_at DESC")

async def create_api_key(user_id: int, permissions: str):
    from db import create_api_key as db_create
    return await db_create(user_id, permissions)

async def revoke_api_key(key_id: int):
    from db import revoke_api_key as db_revoke
    await db_revoke(key_id)

async def get_subscriptions():
    return await fetch("SELECT u.user_id, u.username, s.plan, s.status, s.end_date, s.auto_renew FROM users u LEFT JOIN subscriptions s ON u.user_id = s.user_id ORDER BY u.user_id")

async def update_subscription(user_id: int, plan: str, status: str, end_date: str, auto_renew: bool):
    await execute("""
        INSERT INTO subscriptions (user_id, plan, status, end_date, auto_renew)
        VALUES ($1, $2, $3, $4::TIMESTAMP, $5)
        ON CONFLICT (user_id) DO UPDATE SET plan=$2, status=$3, end_date=$4::TIMESTAMP, auto_renew=$5
    """, user_id, plan, status, end_date, auto_renew)

async def grant_achievement(user_id: int, achievement: str):
    from db import grant_achievement as db_grant
    await db_grant(user_id, achievement)

async def get_achievements():
    return await fetch("SELECT u.username, a.achievement, a.earned_at FROM achievements a JOIN users u ON a.user_id = u.user_id ORDER BY a.earned_at DESC LIMIT 50")

async def get_ranks():
    return await fetch("SELECT u.username, r.level, r.xp FROM ranks r JOIN users u ON r.user_id = u.user_id ORDER BY r.level DESC LIMIT 20")