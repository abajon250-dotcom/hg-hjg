import aiosqlite
from datetime import datetime, timedelta
from typing import List, Dict, Optional, Tuple
from config import ADMIN_IDS   # для автоматического назначения роли админа

DATABASE = "esim_bot.db"

# ------------------------------------------------------------
# Инициализация таблиц (создание, если не существуют)
# ------------------------------------------------------------
async def init_db():
    async with aiosqlite.connect(DATABASE) as db:
        # Таблица пользователей
        await db.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id INTEGER PRIMARY KEY,
                username TEXT,
                full_name TEXT,
                registered_at TIMESTAMP,
                total_earned REAL DEFAULT 0,
                earned_today REAL DEFAULT 0,
                total_qr INTEGER DEFAULT 0,
                crypto_balance REAL DEFAULT 0,
                referrer_id INTEGER,
                referral_earnings REAL DEFAULT 0,
                terms_accepted BOOLEAN DEFAULT 0,
                role TEXT DEFAULT 'user',
                permissions TEXT DEFAULT ''
            )
        """)
        # Таблица заявок (eSIM)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS qr_submissions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                operator TEXT,
                price REAL,
                phone TEXT,
                photo_file_id TEXT,
                status TEXT DEFAULT 'pending',
                submitted_at TIMESTAMP,
                reviewed_at TIMESTAMP,
                admin_id INTEGER,
                earned_amount REAL DEFAULT 0,
                hold_until TIMESTAMP,
                region TEXT,
                reject_reason TEXT,
                taken_by INTEGER,
                taken_at TIMESTAMP
            )
        """)
        # Таблица операторов
        await db.execute("""
            CREATE TABLE IF NOT EXISTS operators (
                name TEXT PRIMARY KEY,
                price_hold REAL,
                price_bh REAL,
                slot_limit INTEGER DEFAULT -1,
                min_minutes INTEGER DEFAULT 50,
                conditions TEXT DEFAULT ''
            )
        """)
        # Таблица бронирований
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                operator TEXT,
                created_at TIMESTAMP,
                used BOOLEAN DEFAULT 0
            )
        """)
        # Таблица настроек
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Таблица ежедневной статистики (опционально)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_qr INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0
            )
        """)
        # Таблица регионов (коды телефонов)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS regions (
                code TEXT PRIMARY KEY,
                name TEXT
            )
        """)
        # Индексы
        await db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_user ON qr_submissions(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_status ON qr_submissions(status)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_bookings_user ON bookings(user_id)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_region ON qr_submissions(region)")
        await db.execute("CREATE INDEX IF NOT EXISTS idx_submissions_taken_by ON qr_submissions(taken_by)")
        await db.commit()

# ------------------------------------------------------------
# Пользователи и роли
# ------------------------------------------------------------
async def register_user(user_id: int, username: str, full_name: str, referrer_id: int = None):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "INSERT OR IGNORE INTO users (user_id, username, full_name, registered_at, referrer_id, terms_accepted) VALUES (?, ?, ?, ?, ?, 0)",
            (user_id, username, full_name, datetime.now(), referrer_id)
        )
        # Назначаем роль admin, если ID в списке администраторов
        role = 'admin' if user_id in ADMIN_IDS else 'user'
        await db.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
        await db.commit()
        if referrer_id and referrer_id != user_id:
            # Бонус пригласившему (1$ на крипто-баланс)
            await update_user_earnings(referrer_id, 1.0, is_referral_bonus=True)

async def accept_terms(user_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET terms_accepted = 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def has_accepted_terms(user_id: int) -> bool:
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT terms_accepted FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] == 1 if row else False

async def get_user(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def update_user_earnings(user_id: int, amount: float, is_referral_bonus=False):
    async with aiosqlite.connect(DATABASE) as db:
        if is_referral_bonus:
            await db.execute(
                "UPDATE users SET referral_earnings = referral_earnings + ?, crypto_balance = crypto_balance + ? WHERE user_id = ?",
                (amount, amount, user_id)
            )
        else:
            await db.execute(
                "UPDATE users SET total_earned = total_earned + ?, earned_today = earned_today + ? WHERE user_id = ?",
                (amount, amount, user_id)
            )
        await db.commit()

async def add_crypto_balance(user_id: int, amount: float):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET crypto_balance = crypto_balance + ? WHERE user_id = ?", (amount, user_id))
        await db.commit()

async def increment_total_qr(user_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET total_qr = total_qr + 1 WHERE user_id = ?", (user_id,))
        await db.commit()

async def set_user_role(user_id: int, role: str):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET role = ? WHERE user_id = ?", (role, user_id))
        await db.commit()

async def get_user_role(user_id: int) -> str:
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT role FROM users WHERE user_id = ?", (user_id,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else "user"

async def add_worker(user_id: int, permissions: str = ""):
    await set_user_role(user_id, "worker")
    if permissions:
        async with aiosqlite.connect(DATABASE) as db:
            await db.execute("UPDATE users SET permissions = ? WHERE user_id = ?", (permissions, user_id))
            await db.commit()

async def remove_worker(user_id: int):
    await set_user_role(user_id, "user")
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE users SET permissions = '' WHERE user_id = ?", (user_id,))

async def get_workers() -> List[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT user_id, username, full_name, permissions FROM users WHERE role = 'worker'") as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

# ------------------------------------------------------------
# Заявки
# ------------------------------------------------------------
async def create_submission(user_id: int, operator: str, price: float, phone: str, photo_file_id: str, region: str = None) -> int:
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute(
            "INSERT INTO qr_submissions (user_id, operator, price, phone, photo_file_id, submitted_at, status, region) VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (user_id, operator, price, phone, photo_file_id, datetime.now(), region)
        )
        await db.commit()
        return cur.lastrowid

async def get_pending_submissions(limit: int = 20) -> List[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM qr_submissions WHERE status = 'pending' ORDER BY submitted_at DESC LIMIT ?", (limit,)) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

async def get_submission(submission_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM qr_submissions WHERE id = ?", (submission_id,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def take_submission(submission_id: int, worker_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'taken', taken_by = ?, taken_at = ? WHERE id = ?",
            (worker_id, datetime.now(), submission_id)
        )
        await db.commit()

async def hold_submission(submission_id: int, admin_id: int, hold_until: datetime):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'hold', reviewed_at = ?, admin_id = ?, hold_until = ? WHERE id = ?",
            (datetime.now(), admin_id, hold_until, submission_id)
        )
        await db.commit()

async def accept_submission_now(submission_id: int, admin_id: int, earned_amount: float):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'accepted', reviewed_at = ?, admin_id = ?, earned_amount = ? WHERE id = ?",
            (datetime.now(), admin_id, earned_amount, submission_id)
        )
        await db.commit()
        sub = await get_submission(submission_id)
        if sub:
            await update_user_earnings(sub['user_id'], earned_amount)
            await increment_total_qr(sub['user_id'])

async def accept_submission_from_hold(submission_id: int, earned_amount: float):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'accepted', earned_amount = ? WHERE id = ?",
            (earned_amount, submission_id)
        )
        await db.commit()
        sub = await get_submission(submission_id)
        if sub:
            await update_user_earnings(sub['user_id'], earned_amount)
            await increment_total_qr(sub['user_id'])

async def mark_submission_failed(submission_id: int, admin_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'failed', reviewed_at = ?, admin_id = ? WHERE id = ?",
            (datetime.now(), admin_id, submission_id)
        )
        await db.commit()

async def mark_submission_blocked(submission_id: int, admin_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'blocked', reviewed_at = ?, admin_id = ? WHERE id = ?",
            (datetime.now(), admin_id, submission_id)
        )
        await db.commit()

async def reject_submission(submission_id: int, admin_id: int, reason: str = 'block'):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE qr_submissions SET status = 'rejected', reviewed_at = ?, admin_id = ?, reject_reason = ? WHERE id = ?",
            (datetime.now(), admin_id, reason, submission_id)
        )
        await db.commit()

async def get_hold_submissions() -> List[Dict]:
    now = datetime.now()
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM qr_submissions WHERE status = 'hold' AND hold_until > ?", (now,)) as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

async def get_taken_submissions(worker_id: int = None) -> List[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        if worker_id:
            cur = await db.execute("SELECT * FROM qr_submissions WHERE status = 'taken' AND taken_by = ?", (worker_id,))
        else:
            cur = await db.execute("SELECT * FROM qr_submissions WHERE status = 'taken'")
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

# ------------------------------------------------------------
# Операторы
# ------------------------------------------------------------
async def get_operators() -> List[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT * FROM operators ORDER BY name") as cur:
            rows = await cur.fetchall()
            return [dict(row) for row in rows]

async def get_operator_price(operator: str, mode: str) -> Optional[float]:
    column = "price_hold" if mode == "hold" else "price_bh"
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute(f"SELECT {column} FROM operators WHERE name = ?", (operator,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else None

async def update_operator_prices(operator: str, price_hold: float, price_bh: float):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute(
            "UPDATE operators SET price_hold = ?, price_bh = ? WHERE name = ?",
            (price_hold, price_bh, operator)
        )
        await db.commit()

async def update_operator_slot_limit(operator: str, limit: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE operators SET slot_limit = ? WHERE name = ?", (limit, operator))
        await db.commit()

async def update_operator_conditions(operator: str, min_minutes: int, conditions: str):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE operators SET min_minutes = ?, conditions = ? WHERE name = ?", (min_minutes, conditions, operator))
        await db.commit()

async def get_operator_conditions(operator: str) -> Dict:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute("SELECT min_minutes, conditions FROM operators WHERE name = ?", (operator,)) as cur:
            row = await cur.fetchone()
            return dict(row) if row else {"min_minutes": 50, "conditions": ""}

# ------------------------------------------------------------
# Бронирования
# ------------------------------------------------------------
async def create_booking(user_id: int, operator: str) -> int:
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute(
            "INSERT INTO bookings (user_id, operator, created_at) VALUES (?, ?, ?)",
            (user_id, operator, datetime.now())
        )
        await db.commit()
        return cur.lastrowid

async def get_active_booking(user_id: int) -> Optional[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        async with db.execute(
            "SELECT * FROM bookings WHERE user_id = ? AND used = 0 ORDER BY created_at DESC LIMIT 1",
            (user_id,)
        ) as cur:
            row = await cur.fetchone()
            return dict(row) if row else None

async def use_booking(booking_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("UPDATE bookings SET used = 1 WHERE id = ?", (booking_id,))
        await db.commit()

async def cancel_booking(booking_id: int):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("DELETE FROM bookings WHERE id = ?", (booking_id,))
        await db.commit()

async def count_active_bookings_for_operator(operator: str) -> int:
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT COUNT(*) FROM bookings WHERE operator = ? AND used = 0", (operator,)) as cur:
            count = await cur.fetchone()
            return count[0] if count else 0

# ------------------------------------------------------------
# Настройки
# ------------------------------------------------------------
async def get_setting(key: str, default: str = None) -> Optional[str]:
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute("SELECT value FROM settings WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
            return row[0] if row else default

async def set_setting(key: str, value: str):
    async with aiosqlite.connect(DATABASE) as db:
        await db.execute("REPLACE INTO settings (key, value) VALUES (?, ?)", (key, value))
        await db.commit()

# ------------------------------------------------------------
# Статистика пользователя (по периодам)
# ------------------------------------------------------------
async def get_user_stats(user_id: int, days: int = None) -> Dict:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        if days is None:
            cur = await db.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'block' THEN 1 ELSE 0 END) as blocked,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'noscan' THEN 1 ELSE 0 END) as noscan,
                    COALESCE(SUM(earned_amount), 0) as sum_earned
                FROM qr_submissions
                WHERE user_id = ?
            """, (user_id,))
        else:
            cur = await db.execute("""
                SELECT
                    COUNT(*) as total,
                    SUM(CASE WHEN status = 'accepted' THEN 1 ELSE 0 END) as accepted,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'block' THEN 1 ELSE 0 END) as blocked,
                    SUM(CASE WHEN status = 'rejected' AND reject_reason = 'noscan' THEN 1 ELSE 0 END) as noscan,
                    COALESCE(SUM(earned_amount), 0) as sum_earned
                FROM qr_submissions
                WHERE user_id = ? AND submitted_at >= datetime('now', ? || ' days')
            """, (user_id, f"-{days}"))
        row = await cur.fetchone()
        return dict(row) if row else {"total":0, "accepted":0, "blocked":0, "noscan":0, "sum_earned":0.0}

async def get_user_qr_last_30_days(user_id: int) -> Tuple[int, List[str]]:
    since = datetime.now() - timedelta(days=30)
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute(
            "SELECT submitted_at FROM qr_submissions WHERE user_id = ? AND status = 'accepted' AND submitted_at >= ?",
            (user_id, since)
        ) as cur:
            rows = await cur.fetchall()
            dates = [row[0][:10] for row in rows]
            return len(rows), list(set(dates))

async def get_today_stats() -> Dict:
    today = datetime.now().date().isoformat()
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute(
            "SELECT COUNT(*), SUM(earned_amount) FROM qr_submissions WHERE status = 'accepted' AND date(submitted_at) = ?",
            (today,)
        ) as cur:
            row = await cur.fetchone()
            return {"total_qr": row[0] or 0, "total_earned": row[1] or 0.0}

async def get_top_users(limit: int = 10) -> List[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        async with db.execute(
            "SELECT user_id, total_earned FROM users ORDER BY total_earned DESC LIMIT ?",
            (limit,)
        ) as cur:
            rows = await cur.fetchall()
            return [{"user_id": r[0], "total_earned": r[1]} for r in rows]

# ------------------------------------------------------------
# Регионы и топ операторов
# ------------------------------------------------------------
async def get_operator_top_regions(operator: str, period_days: int = 7) -> List[Dict]:
    async with aiosqlite.connect(DATABASE) as db:
        db.row_factory = aiosqlite.Row
        cur = await db.execute("""
            SELECT r.name as region_name, COUNT(*) as cnt
            FROM qr_submissions q
            JOIN regions r ON q.region = r.code
            WHERE q.operator = ? AND q.status = 'accepted' AND q.submitted_at >= datetime('now', ? || ' days')
            GROUP BY q.region
            ORDER BY cnt DESC
            LIMIT 5
        """, (operator, f"-{period_days}"))
        rows = await cur.fetchall()
        return [dict(row) for row in rows]

# ------------------------------------------------------------
# Реферальная система (процент бонуса)
# ------------------------------------------------------------
async def get_referral_percent(referrer_id: int) -> float:
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute("""
            SELECT COUNT(q.id) as total_qr
            FROM qr_submissions q
            JOIN users u ON q.user_id = u.user_id
            WHERE u.referrer_id = ? AND q.status = 'accepted' AND q.submitted_at >= datetime('now', '-30 days')
        """, (referrer_id,))
        row = await cur.fetchone()
        qr_count = row[0] if row else 0
        if qr_count >= 200: return 4.0
        elif qr_count >= 101: return 3.5
        elif qr_count >= 61: return 3.0
        elif qr_count >= 41: return 2.0
        elif qr_count >= 21: return 1.0
        else: return 0.0

async def get_referral_stats(user_id: int) -> Dict:
    async with aiosqlite.connect(DATABASE) as db:
        cur = await db.execute("SELECT COUNT(*) FROM users WHERE referrer_id = ?", (user_id,))
        count = (await cur.fetchone())[0]
        user = await get_user(user_id)
        earnings = user['referral_earnings'] if user else 0
        return {"count": count, "earnings": earnings}