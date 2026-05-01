import asyncio
import aiosqlite

DATABASE = "esim_bot.db"

async def create_tables_and_data():
    print(f"Создаю/обновляю базу данных {DATABASE}...")
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
        # Таблица заявок
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
        # Операторы
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
        # Бронирования
        await db.execute("""
            CREATE TABLE IF NOT EXISTS bookings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                operator TEXT,
                created_at TIMESTAMP,
                used BOOLEAN DEFAULT 0
            )
        """)
        # Настройки
        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)
        # Ежедневная статистика
        await db.execute("""
            CREATE TABLE IF NOT EXISTS daily_stats (
                date TEXT PRIMARY KEY,
                total_qr INTEGER DEFAULT 0,
                total_earned REAL DEFAULT 0
            )
        """)
        # Регионы
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

        # ------ Заполнение начальными данными ------
        operators = [
            ("Билайн", 15.0, 12.0, -1, 50, ""),
            ("Газпром", 28.0, 22.0, -1, 50, ""),
            ("МТС", 18.0, 14.0, -1, 50, ""),
            ("Сбер", 12.0, 9.0, -1, 50, ""),
            ("ВТБ", 25.0, 20.0, -1, 50, ""),
            ("Добросвязь", 13.0, 10.0, -1, 50, ""),
            ("Мегафон", 14.0, 11.0, -1, 50, ""),
            ("Т2", 14.0, 11.0, -1, 50, ""),
            ("Тинькофф", 14.0, 11.0, -1, 50, ""),
            ("Миранда", 11.0, 9.0, -1, 50, ""),
            ("Волна", 12.0, 10.0, -1, 50, ""),
            ("Йота", 14.0, 11.0, -1, 50, ""),
        ]
        for op in operators:
            await db.execute("""
                INSERT OR IGNORE INTO operators (name, price_hold, price_bh, slot_limit, min_minutes, conditions)
                VALUES (?, ?, ?, ?, ?, ?)
            """, op)

        await db.execute("INSERT OR IGNORE INTO settings (key, value) VALUES ('sale_mode', 'hold')")

        regions = [
            ("901", "г. Санкт-Петербург и Ленинградская область"),
            ("902", "г. Санкт-Петербург и Ленинградская область"),
            ("903", "г. Санкт-Петербург и Ленинградская область"),
            ("904", "г. Санкт-Петербург и Ленинградская область"),
            ("905", "г. Санкт-Петербург и Ленинградская область"),
            ("906", "г. Санкт-Петербург и Ленинградская область"),
            ("909", "г. Санкт-Петербург и Ленинградская область"),
            ("910", "Москва и Московская область"),
            ("915", "Москва и Московская область"),
            ("916", "Москва и Московская область"),
            ("917", "Москва и Московская область"),
            ("925", "Москва и Московская область"),
            ("926", "Москва и Московская область"),
            ("929", "Москва и Московская область"),
            ("930", "Москва и Московская область"),
            ("937", "Москва и Московская область"),
            ("938", "Москва и Московская область"),
            ("939", "Москва и Московская область"),
            ("958", "Москва и Московская область"),
            ("977", "Москва и Московская область"),
            ("985", "Москва и Московская область"),
            ("986", "Москва и Московская область"),
            ("987", "Москва и Московская область"),
            ("988", "Москва и Московская область"),
            ("989", "Москва и Московская область"),
            ("995", "Москва и Московская область"),
            ("981", "Иркутская обл."),
            ("982", "Иркутская обл."),
            ("983", "Иркутская обл."),
            ("984", "Иркутская обл."),
        ]
        for code, name in regions:
            await db.execute("INSERT OR IGNORE INTO regions (code, name) VALUES (?, ?)", (code, name))

        await db.commit()
    print("✅ База данных успешно создана и заполнена начальными данными.")

if __name__ == "__main__":
    asyncio.run(create_tables_and_data())