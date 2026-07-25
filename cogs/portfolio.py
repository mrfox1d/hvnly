import datetime
import disnake
from disnake.ext import commands
from disnake import ui, Embed, ButtonStyle
import aiosqlite

DB_PATH = "database.db"
DESIGNER_ROLE_ID = 1529564459440275466
PORTFOLIO_SHOWCASE_CHANNEL_ID = 1529565799650693130

WORKS_PER_PAGE = 1
REVIEWS_PER_PAGE = 3


# ---------------------------------------------------------------------------
# Работа с базой данных
# ---------------------------------------------------------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS portfolio_works (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                designer_id INTEGER NOT NULL,
                image_url TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                message_id INTEGER
            )
        """)
        try:
            await db.execute("ALTER TABLE portfolio_works ADD COLUMN message_id INTEGER")
        except aiosqlite.OperationalError:
            pass
        await db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                designer_id INTEGER NOT NULL,
                client_id INTEGER NOT NULL,
                rating INTEGER NOT NULL,
                comment TEXT,
                created_at TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS designer_status (
                designer_id INTEGER PRIMARY KEY,
                status TEXT NOT NULL DEFAULT 'free'
            )
        """)
        await db.commit()


async def add_work(designer_id: int, image_url: str, description: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO portfolio_works (designer_id, image_url, description, created_at) VALUES (?, ?, ?, ?)",
            (designer_id, image_url, description, datetime.datetime.utcnow().isoformat())
        )
        await db.commit()
        return cursor.lastrowid


async def replace_work(work_id: int, designer_id: int, image_url: str, description: str | None) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        if description is None:
            cursor = await db.execute(
                "UPDATE portfolio_works SET image_url = ? WHERE id = ? AND designer_id = ?",
                (image_url, work_id, designer_id)
            )
        else:
            cursor = await db.execute(
                "UPDATE portfolio_works SET image_url = ?, description = ? WHERE id = ? AND designer_id = ?",
                (image_url, description, work_id, designer_id)
            )
        await db.commit()
        return cursor.rowcount > 0


async def get_work(work_id: int, designer_id: int) -> tuple | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, image_url, description, created_at, message_id FROM portfolio_works WHERE id = ? AND designer_id = ?",
            (work_id, designer_id)
        ) as cursor:
            return await cursor.fetchone()


async def set_work_message_id(work_id: int, message_id: int | None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE portfolio_works SET message_id = ? WHERE id = ?", (message_id, work_id))
        await db.commit()


async def remove_work(work_id: int, designer_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM portfolio_works WHERE id = ? AND designer_id = ?",
            (work_id, designer_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def get_works(designer_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, image_url, description, created_at FROM portfolio_works WHERE designer_id = ? ORDER BY id DESC",
            (designer_id,)
        ) as cursor:
            return await cursor.fetchall()


async def add_review(designer_id: int, client_id: int, rating: int, comment: str) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO reviews (designer_id, client_id, rating, comment, created_at) VALUES (?, ?, ?, ?, ?)",
            (designer_id, client_id, rating, comment, datetime.datetime.utcnow().isoformat())
        )
        await db.commit()
        return cursor.lastrowid


async def get_reviews(designer_id: int) -> list[tuple]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT client_id, rating, comment, created_at FROM reviews WHERE designer_id = ? ORDER BY id DESC",
            (designer_id,)
        ) as cursor:
            return await cursor.fetchall()


async def get_avg_rating(designer_id: int) -> tuple[float, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT AVG(rating), COUNT(*) FROM reviews WHERE designer_id = ?",
            (designer_id,)
        ) as cursor:
            row = await cursor.fetchone()
            avg = round(row[0], 1) if row and row[0] is not None else 0.0
            count = row[1] if row else 0
            return avg, count


async def get_status(designer_id: int) -> str:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT status FROM designer_status WHERE designer_id = ?",
            (designer_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else "free"


async def set_status(designer_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO designer_status (designer_id, status) VALUES (?, ?)
            ON CONFLICT(designer_id) DO UPDATE SET status = excluded.status
        """, (designer_id, status))
        await db.commit()


def stars(rating: float) -> str:
    full = int(round(rating))
    return "⭐" * full + "▫️" * (5 - full)


# ---------------------------------------------------------------------------
# UI: профиль дизайнера
# ---------------------------------------------------------------------------

class DesignerProfileView(ui.View):
    """Кнопки просмотра портфолио и отзывов дизайнера + смена статуса владельцем."""

    def __init__(self, designer: disnake.Member, viewer_id: int):
        super().__init__(timeout=180)
        self.designer = designer
        self.viewer_id = viewer_id
        self.works_page = 0
        self.reviews_page = 0

        if viewer_id != designer.id:
            self.remove_item(self.toggle_status)

    async def _build_profile_embed(self) -> Embed:
        avg, count = await get_avg_rating(self.designer.id)
        status = await get_status(self.designer.id)
        works = await get_works(self.designer.id)

        embed = Embed(
            title=f"🎨 Профиль дизайнера — {self.designer.display_name}",
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        embed.set_thumbnail(url=self.designer.display_avatar.url)
        embed.add_field(name="Статус", value="🟢 Свободен" if status == "free" else "🔴 Занят", inline=True)
        embed.add_field(name="Работ в портфолио", value=str(len(works)), inline=True)
        embed.add_field(
            name="Рейтинг",
            value=f"{stars(avg)} ({avg}/5, {count} отзыв.)" if count else "Пока нет отзывов",
            inline=True
        )
        embed.set_footer(text="Heavenly Design © 2026")
        return embed

    @ui.button(label="Профиль", style=ButtonStyle.primary, emoji="👤", custom_id="profile_overview")
    async def overview(self, button: ui.Button, inter: disnake.MessageInteraction):
        embed = await self._build_profile_embed()
        await inter.response.edit_message(embed=embed, view=self)

    @ui.button(label="Портфолио", style=ButtonStyle.secondary, emoji="🖼️", custom_id="profile_portfolio")
    async def portfolio(self, button: ui.Button, inter: disnake.MessageInteraction):
        works = await get_works(self.designer.id)
        if not works:
            await inter.response.send_message("У этого дизайнера пока нет работ в портфолио.", ephemeral=True)
            return

        self.works_page = 0
        embed = self._work_embed(works, self.works_page)
        await inter.response.edit_message(embed=embed, view=self)

    def _work_embed(self, works: list[tuple], page: int) -> Embed:
        work_id, image_url, description, created_at = works[page]
        embed = Embed(
            title=f"🖼️ Портфолио — {self.designer.display_name}",
            description=description or "Без описания",
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        embed.set_image(url=image_url)
        embed.set_footer(text=f"Работа {page + 1}/{len(works)} • ID: {work_id} • Heavenly Design © 2026")
        return embed

    @ui.button(label="Отзывы", style=ButtonStyle.secondary, emoji="⭐", custom_id="profile_reviews")
    async def reviews(self, button: ui.Button, inter: disnake.MessageInteraction):
        reviews = await get_reviews(self.designer.id)
        if not reviews:
            await inter.response.send_message("У этого дизайнера пока нет отзывов.", ephemeral=True)
            return

        self.reviews_page = 0
        embed = self._reviews_embed(reviews, self.reviews_page)
        await inter.response.edit_message(embed=embed, view=self)

    def _reviews_embed(self, reviews: list[tuple], page: int) -> Embed:
        start = page * REVIEWS_PER_PAGE
        chunk = reviews[start:start + REVIEWS_PER_PAGE]
        embed = Embed(
            title=f"⭐ Отзывы — {self.designer.display_name}",
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        for client_id, rating, comment, created_at in chunk:
            embed.add_field(
                name=f"{stars(rating)} от <@{client_id}>",
                value=comment or "Без комментария",
                inline=False
            )
        total_pages = max(1, (len(reviews) + REVIEWS_PER_PAGE - 1) // REVIEWS_PER_PAGE)
        embed.set_footer(text=f"Страница {page + 1}/{total_pages} • Heavenly Design © 2026")
        return embed

    @ui.button(label="Сменить статус", style=ButtonStyle.success, emoji="🔄", custom_id="profile_toggle_status", row=1)
    async def toggle_status(self, button: ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.designer.id:
            await inter.response.send_message("❌ Менять статус может только сам дизайнер.", ephemeral=True)
            return

        if not any(role.id == DESIGNER_ROLE_ID for role in inter.author.roles):
            await inter.response.send_message("❌ У вас больше нет роли дизайнера.", ephemeral=True)
            return

        current = await get_status(self.designer.id)
        new_status = "busy" if current == "free" else "free"
        await set_status(self.designer.id, new_status)

        embed = await self._build_profile_embed()
        await inter.response.edit_message(embed=embed, view=self)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Portfolio(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        await init_db()

    def _is_designer(self, member: disnake.Member) -> bool:
        return any(role.id == DESIGNER_ROLE_ID for role in member.roles)

    async def _get_showcase_channel(self) -> disnake.TextChannel | None:
        channel = self.bot.get_channel(PORTFOLIO_SHOWCASE_CHANNEL_ID)
        if not channel:
            try:
                channel = await self.bot.fetch_channel(PORTFOLIO_SHOWCASE_CHANNEL_ID)
            except (disnake.NotFound, disnake.Forbidden):
                return None
        return channel

    def _showcase_embed(self, designer: disnake.Member, image_url: str, description: str, work_id: int) -> Embed:
        embed = Embed(
            title=f"🖼️ Новая работа в портфолио — {designer.display_name}",
            description=description or "Без описания",
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        embed.set_image(url=image_url)
        embed.set_author(name=designer.display_name, icon_url=designer.display_avatar.url)
        embed.set_footer(text=f"ID работы: {work_id} • Heavenly Design © 2026")
        return embed

    @commands.slash_command(name="portfolio_add", description="Добавить работу в своё портфолио")
    async def portfolio_add(
        self,
        inter: disnake.ApplicationCommandInteraction,
        attachment: disnake.Attachment,
        description: str = commands.Param(description="Краткое описание работы", max_length=500),
    ):
        if not self._is_designer(inter.author):
            await inter.response.send_message("❌ Эта команда доступна только дизайнерам.", ephemeral=True)
            return

        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            await inter.response.send_message("❌ Нужно прикрепить изображение.", ephemeral=True)
            return

        work_id = await add_work(inter.author.id, attachment.url, description)

        showcase_channel = await self._get_showcase_channel()
        if showcase_channel:
            try:
                msg = await showcase_channel.send(embed=self._showcase_embed(inter.author, attachment.url, description, work_id))
                await set_work_message_id(work_id, msg.id)
            except disnake.HTTPException:
                pass

        embed = Embed(
            description=f"✅ Работа добавлена в портфолио (ID: `{work_id}`).",
            color=disnake.Color.green()
        )
        embed.set_thumbnail(url=attachment.url)
        await inter.response.send_message(embed=embed, ephemeral=True)

    @commands.slash_command(name="portfolio_replace", description="Заменить существующую работу в портфолио")
    async def portfolio_replace(
        self,
        inter: disnake.ApplicationCommandInteraction,
        work_id: int = commands.Param(description="ID работы, которую нужно заменить"),
        attachment: disnake.Attachment = commands.Param(description="Новое изображение"),
        description: str = commands.Param(default=None, description="Новое описание (необязательно)", max_length=500),
    ):
        if not self._is_designer(inter.author):
            await inter.response.send_message("❌ Эта команда доступна только дизайнерам.", ephemeral=True)
            return

        if not attachment.content_type or not attachment.content_type.startswith("image/"):
            await inter.response.send_message("❌ Нужно прикрепить изображение.", ephemeral=True)
            return

        existing = await get_work(work_id, inter.author.id)
        if not existing:
            await inter.response.send_message(
                "❌ Работа с таким ID не найдена или принадлежит другому дизайнеру.", ephemeral=True
            )
            return

        success = await replace_work(work_id, inter.author.id, attachment.url, description)
        if not success:
            await inter.response.send_message(
                "❌ Работа с таким ID не найдена или принадлежит другому дизайнеру.", ephemeral=True
            )
            return

        final_description = description if description is not None else existing[2]
        message_id = existing[4]

        showcase_channel = await self._get_showcase_channel()
        if showcase_channel:
            new_embed = self._showcase_embed(inter.author, attachment.url, final_description, work_id)
            edited = False
            if message_id:
                try:
                    msg = await showcase_channel.fetch_message(message_id)
                    await msg.edit(embed=new_embed)
                    edited = True
                except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                    edited = False
            if not edited:
                try:
                    msg = await showcase_channel.send(embed=new_embed)
                    await set_work_message_id(work_id, msg.id)
                except disnake.HTTPException:
                    pass

        embed = Embed(
            description=f"🔄 Работа `{work_id}` заменена.",
            color=disnake.Color.green()
        )
        embed.set_thumbnail(url=attachment.url)
        await inter.response.send_message(embed=embed, ephemeral=True)

    @commands.slash_command(name="portfolio_remove", description="Удалить работу из своего портфолио")
    async def portfolio_remove(
        self,
        inter: disnake.ApplicationCommandInteraction,
        work_id: int = commands.Param(description="ID работы для удаления"),
    ):
        if not self._is_designer(inter.author):
            await inter.response.send_message("❌ Эта команда доступна только дизайнерам.", ephemeral=True)
            return

        existing = await get_work(work_id, inter.author.id)
        if not existing:
            await inter.response.send_message(
                "❌ Работа с таким ID не найдена или принадлежит другому дизайнеру.", ephemeral=True
            )
            return

        success = await remove_work(work_id, inter.author.id)
        if not success:
            await inter.response.send_message(
                "❌ Работа с таким ID не найдена или принадлежит другому дизайнеру.", ephemeral=True
            )
            return

        message_id = existing[4]
        showcase_channel = await self._get_showcase_channel()
        if showcase_channel and message_id:
            try:
                msg = await showcase_channel.fetch_message(message_id)
                await msg.delete()
            except (disnake.NotFound, disnake.Forbidden, disnake.HTTPException):
                pass

        await inter.response.send_message(f"🗑️ Работа `{work_id}` удалена из портфолио.", ephemeral=True)

    @commands.slash_command(name="profile", description="Посмотреть профиль дизайнера (портфолио, отзывы, статус)")
    async def profile(
        self,
        inter: disnake.ApplicationCommandInteraction,
        designer: disnake.Member = commands.Param(description="Дизайнер, чей профиль нужно посмотреть"),
    ):
        if not self._is_designer(designer):
            await inter.response.send_message("❌ У этого пользователя нет роли дизайнера.", ephemeral=True)
            return

        view = DesignerProfileView(designer, inter.author.id)
        embed = await view._build_profile_embed()
        await inter.response.send_message(embed=embed, view=view)

    @commands.slash_command(name="review", description="Оставить отзыв дизайнеру")
    async def review(
        self,
        inter: disnake.ApplicationCommandInteraction,
        designer: disnake.Member = commands.Param(description="Дизайнер, которому оставляете отзыв"),
        rating: int = commands.Param(description="Оценка от 1 до 5", ge=1, le=5),
        comment: str = commands.Param(description="Текст отзыва", max_length=500),
    ):
        if not self._is_designer(designer):
            await inter.response.send_message("❌ У этого пользователя нет роли дизайнера.", ephemeral=True)
            return

        if designer.id == inter.author.id:
            await inter.response.send_message("❌ Нельзя оставить отзыв самому себе.", ephemeral=True)
            return

        await add_review(designer.id, inter.author.id, rating, comment)

        embed = Embed(
            description=f"✅ Отзыв для {designer.mention} добавлен: {stars(rating)}",
            color=disnake.Color.green()
        )
        await inter.response.send_message(embed=embed, ephemeral=True)


def setup(bot: commands.Bot):
    bot.add_cog(Portfolio(bot))