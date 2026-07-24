import aiosqlite

DB_PATH = "database.db"

async def init_db():
    """Единая инициализация всех таблиц базы данных"""
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS orders (
                channel_id INTEGER PRIMARY KEY,
                customer_id INTEGER NOT NULL,
                task TEXT NOT NULL,
                service TEXT NOT NULL,
                difficulty TEXT NOT NULL,
                currency TEXT NOT NULL,
                price INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'unpaid',
                designer_id INTEGER,
                work_done_at TIMESTAMP,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN designer_id INTEGER")
        except aiosqlite.OperationalError:
            pass
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN work_done_at TIMESTAMP")
        except aiosqlite.OperationalError:
            pass

        await db.execute("""
            CREATE TABLE IF NOT EXISTS warnings (
                user_id INTEGER PRIMARY KEY,
                warnings INTEGER NOT NULL DEFAULT 0
            )
        """)

        await db.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value INTEGER NOT NULL DEFAULT 1
            )
        """)

        await db.commit()