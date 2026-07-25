import aiosqlite

DB_PATH = "database.db"


async def _migrate_orders_price_nullable(db: aiosqlite.Connection):
    """Если таблица orders уже существует со старой схемой (price NOT NULL),
    пересоздаёт её без этого ограничения, сохраняя все данные."""
    async with db.execute("PRAGMA table_info(orders)") as cursor:
        columns_info = await cursor.fetchall()

    if not columns_info:
        return  # таблицы ещё нет — CREATE TABLE ниже создаст её сразу правильно

    price_col = next((c for c in columns_info if c[1] == "price"), None)
    if price_col is None or price_col[3] == 0:
        return  # колонки нет (странно) или NOT NULL уже снят — миграция не нужна

    col_names = [c[1] for c in columns_info]

    new_cols_sql = []
    for cid, name, ctype, notnull, dflt, pk in columns_info:
        col_def = f"{name} {ctype}" if ctype else name
        if name == "price":
            pass  # без NOT NULL
        else:
            if notnull:
                col_def += " NOT NULL"
            if dflt is not None:
                col_def += f" DEFAULT {dflt}"
        if pk:
            col_def += " PRIMARY KEY"
        new_cols_sql.append(col_def)

    await db.execute(f"CREATE TABLE orders_new ({', '.join(new_cols_sql)})")
    col_list = ", ".join(col_names)
    await db.execute(f"INSERT INTO orders_new ({col_list}) SELECT {col_list} FROM orders")
    await db.execute("DROP TABLE orders")
    await db.execute("ALTER TABLE orders_new RENAME TO orders")


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
                price INTEGER,
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

        await _migrate_orders_price_nullable(db)

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