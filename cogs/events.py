import random
import re
import time
import aiosqlite
import disnake
from disnake.ext import commands, tasks
from disnake.ext.commands import Bot, Cog, Param
from disnake import ui, Embed, ButtonStyle

DB_PATH = "database.db"
GIVEAWAY_COLOR = 0x2B2D31
GIVEAWAY_END_COLOR = disnake.Color.dark_grey()

DURATION_REGEX = re.compile(r"(\d+)\s*([dhms])", re.IGNORECASE)
DURATION_UNITS = {"d": 86400, "h": 3600, "m": 60, "s": 1}


def parse_duration(text: str) -> int | None:
    """Парсит строку вида '1d12h30m' / '2h' / '45m' в количество секунд.
    Возвращает None, если строка не распознана."""
    matches = DURATION_REGEX.findall(text.strip().lower())
    if not matches:
        return None
    total = 0
    for value, unit in matches:
        total += int(value) * DURATION_UNITS[unit]
    return total if total > 0 else None


def format_duration_input_hint() -> str:
    return "Примеры: `10m`, `1h30m`, `2d`, `1d12h30m`"


# ---------------------------------------------------------------------------
# Работа с базой данных
# ---------------------------------------------------------------------------

async def init_giveaway_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaways (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                guild_id INTEGER NOT NULL,
                channel_id INTEGER NOT NULL,
                message_id INTEGER,
                host_id INTEGER NOT NULL,
                prize TEXT NOT NULL,
                winners_count INTEGER NOT NULL DEFAULT 1,
                required_role_id INTEGER,
                end_time INTEGER NOT NULL,
                ended INTEGER NOT NULL DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS giveaway_entries (
                giveaway_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                PRIMARY KEY (giveaway_id, user_id)
            )
        """)
        await db.commit()


async def create_giveaway_db(guild_id, channel_id, host_id, prize, winners_count, end_time, required_role_id) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO giveaways (guild_id, channel_id, host_id, prize, winners_count, required_role_id, end_time) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (guild_id, channel_id, host_id, prize, winners_count, required_role_id, end_time)
        )
        await db.commit()
        return cursor.lastrowid


async def set_giveaway_message_id(giveaway_id: int, message_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE giveaways SET message_id = ? WHERE id = ?", (message_id, giveaway_id))
        await db.commit()


def _row_to_dict(row) -> dict:
    return {
        "id": row[0],
        "guild_id": row[1],
        "channel_id": row[2],
        "message_id": row[3],
        "host_id": row[4],
        "prize": row[5],
        "winners_count": row[6],
        "required_role_id": row[7],
        "end_time": row[8],
        "ended": bool(row[9]),
    }


GIVEAWAY_COLUMNS = "id, guild_id, channel_id, message_id, host_id, prize, winners_count, required_role_id, end_time, ended"


async def get_giveaway(giveaway_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT {GIVEAWAY_COLUMNS} FROM giveaways WHERE id = ?", (giveaway_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None


async def get_giveaway_by_message(message_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(f"SELECT {GIVEAWAY_COLUMNS} FROM giveaways WHERE message_id = ?", (message_id,)) as cursor:
            row = await cursor.fetchone()
            return _row_to_dict(row) if row else None


async def get_active_giveaways(guild_id: int | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        if guild_id is None:
            query = f"SELECT {GIVEAWAY_COLUMNS} FROM giveaways WHERE ended = 0 ORDER BY end_time ASC"
            params = ()
        else:
            query = f"SELECT {GIVEAWAY_COLUMNS} FROM giveaways WHERE ended = 0 AND guild_id = ? ORDER BY end_time ASC"
            params = (guild_id,)
        async with db.execute(query, params) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(r) for r in rows]


async def get_expired_giveaways() -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        now = int(time.time())
        async with db.execute(
            f"SELECT {GIVEAWAY_COLUMNS} FROM giveaways WHERE ended = 0 AND end_time <= ?", (now,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [_row_to_dict(r) for r in rows]


async def mark_giveaway_ended(giveaway_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE giveaways SET ended = 1 WHERE id = ?", (giveaway_id,))
        await db.commit()


async def add_entry(giveaway_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        try:
            await db.execute(
                "INSERT INTO giveaway_entries (giveaway_id, user_id) VALUES (?, ?)", (giveaway_id, user_id)
            )
            await db.commit()
            return True
        except aiosqlite.IntegrityError:
            return False


async def remove_entry(giveaway_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "DELETE FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id)
        )
        await db.commit()
        return cursor.rowcount > 0


async def is_entered(giveaway_id: int, user_id: int) -> bool:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT 1 FROM giveaway_entries WHERE giveaway_id = ? AND user_id = ?", (giveaway_id, user_id)
        ) as cursor:
            return (await cursor.fetchone()) is not None


async def get_entries(giveaway_id: int) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT user_id FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ) as cursor:
            rows = await cursor.fetchall()
            return [r[0] for r in rows]


async def count_entries(giveaway_id: int) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT COUNT(*) FROM giveaway_entries WHERE giveaway_id = ?", (giveaway_id,)
        ) as cursor:
            row = await cursor.fetchone()
            return row[0] if row else 0


# ---------------------------------------------------------------------------
# Embed-конструктор
# ---------------------------------------------------------------------------

def build_giveaway_embed(giveaway: dict, entries_count: int) -> Embed:
    ended = giveaway["ended"]
    color = GIVEAWAY_END_COLOR if ended else GIVEAWAY_COLOR

    role_line = f"<@&{giveaway['required_role_id']}>" if giveaway["required_role_id"] else "Нет ограничений"
    status_line = (
        "🔒 Розыгрыш завершён" if ended
        else f"⏳ Окончание: <t:{giveaway['end_time']}:R> (<t:{giveaway['end_time']}:f>)"
    )

    embed = Embed(
        title="🎉 РОЗЫГРЫШ!" if not ended else "🎉 РОЗЫГРЫШ ЗАВЕРШЁН",
        description=(
            f"### 🏆 Приз: **{giveaway['prize']}**\n\n"
            f"**Организатор:** <@{giveaway['host_id']}>\n"
            f"**Победителей:** {giveaway['winners_count']}\n"
            f"**Условие участия:** {role_line}\n"
            f"{status_line}\n\n"
            f"-# Нажмите «🎉 Участвовать», чтобы принять участие. Повторное нажатие отменяет участие."
        ),
        color=color
    )
    embed.set_footer(text=f"ID розыгрыша: {giveaway['id']} • Участников: {entries_count} • Heavenly Design © 2026")
    return embed


# ---------------------------------------------------------------------------
# Персистентная view на сообщении розыгрыша
# ---------------------------------------------------------------------------

def _is_giveaway_manager(member: disnake.Member, giveaway: dict) -> bool:
    return member.id == giveaway["host_id"] or member.guild_permissions.administrator or member.guild_permissions.manage_guild


class GiveawayView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Участвовать", style=ButtonStyle.success, emoji="🎉", custom_id="giveaway_join")
    async def join(self, button: ui.Button, inter: disnake.MessageInteraction):
        giveaway = await get_giveaway_by_message(inter.message.id)
        if not giveaway:
            await inter.response.send_message("❌ Розыгрыш не найден в базе данных.", ephemeral=True)
            return

        if giveaway["ended"]:
            await inter.response.send_message("❌ Этот розыгрыш уже завершён.", ephemeral=True)
            return

        if giveaway["required_role_id"]:
            has_role = any(r.id == giveaway["required_role_id"] for r in inter.author.roles)
            if not has_role:
                await inter.response.send_message(
                    f"❌ Для участия нужна роль <@&{giveaway['required_role_id']}>.", ephemeral=True
                )
                return

        already_in = await is_entered(giveaway["id"], inter.author.id)
        if already_in:
            await remove_entry(giveaway["id"], inter.author.id)
            await inter.response.send_message("🚪 Вы отменили участие в розыгрыше.", ephemeral=True)
        else:
            await add_entry(giveaway["id"], inter.author.id)
            await inter.response.send_message("🎉 Вы участвуете в розыгрыше! Удачи!", ephemeral=True)

        new_count = await count_entries(giveaway["id"])
        try:
            await inter.message.edit(embed=build_giveaway_embed(giveaway, new_count))
        except disnake.HTTPException:
            pass

    @ui.button(label="Реролл", style=ButtonStyle.secondary, emoji="🔁", custom_id="giveaway_reroll")
    async def reroll(self, button: ui.Button, inter: disnake.MessageInteraction):
        giveaway = await get_giveaway_by_message(inter.message.id)
        if not giveaway:
            await inter.response.send_message("❌ Розыгрыш не найден в базе данных.", ephemeral=True)
            return

        if not _is_giveaway_manager(inter.author, giveaway):
            await inter.response.send_message("❌ Реролл может сделать только организатор или администрация.", ephemeral=True)
            return

        if not giveaway["ended"]:
            await inter.response.send_message("❌ Сначала дождитесь окончания розыгрыша (или завершите его досрочно).", ephemeral=True)
            return

        entries = await get_entries(giveaway["id"])
        if not entries:
            await inter.response.send_message("❌ Участников не было — реролл невозможен.", ephemeral=True)
            return

        winners = random.sample(entries, min(giveaway["winners_count"], len(entries)))
        winners_mentions = ", ".join(f"<@{uid}>" for uid in winners)

        await inter.response.send_message("✅ Реролл выполнен!", ephemeral=True)

        reroll_embed = Embed(
            description=(
                f"### 🔁 Реролл розыгрыша!\n"
                f"**Приз:** {giveaway['prize']}\n"
                f"**Новые победители:** {winners_mentions}\n\n"
                f"Поздравляем! 🎉"
            ),
            color=disnake.Color.gold()
        )
        reroll_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(content=winners_mentions, embed=reroll_embed)

    @ui.button(label="Завершить", style=ButtonStyle.danger, emoji="⏹️", custom_id="giveaway_end")
    async def end_now(self, button: ui.Button, inter: disnake.MessageInteraction):
        giveaway = await get_giveaway_by_message(inter.message.id)
        if not giveaway:
            await inter.response.send_message("❌ Розыгрыш не найден в базе данных.", ephemeral=True)
            return

        if not _is_giveaway_manager(inter.author, giveaway):
            await inter.response.send_message("❌ Завершить розыгрыш может только организатор или администрация.", ephemeral=True)
            return

        if giveaway["ended"]:
            await inter.response.send_message("ℹ️ Розыгрыш уже завершён.", ephemeral=True)
            return

        await inter.response.send_message("⏹️ Розыгрыш завершается досрочно…", ephemeral=True)
        cog: Giveaway = inter.bot.get_cog("Giveaway")
        if cog:
            await cog.finish_giveaway(giveaway, message=inter.message)


# ---------------------------------------------------------------------------
# Cog
# ---------------------------------------------------------------------------

class Giveaway(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.check_giveaways.start()

    def cog_unload(self):
        self.check_giveaways.cancel()

    @Cog.listener()
    async def on_ready(self):
        await init_giveaway_db()
        self.bot.add_view(GiveawayView())

    @tasks.loop(seconds=20)
    async def check_giveaways(self):
        expired = await get_expired_giveaways()
        for giveaway in expired:
            await self.finish_giveaway(giveaway)

    @check_giveaways.before_loop
    async def before_check_giveaways(self):
        await self.bot.wait_until_ready()

    async def finish_giveaway(self, giveaway: dict, message: disnake.Message | None = None):
        """Общая логика завершения розыгрыша: и по таймеру, и вручную через кнопку/команду."""
        await mark_giveaway_ended(giveaway["id"])

        if message is None:
            channel = self.bot.get_channel(giveaway["channel_id"])
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(giveaway["channel_id"])
                except (disnake.NotFound, disnake.Forbidden):
                    channel = None
            if channel and giveaway["message_id"]:
                try:
                    message = await channel.fetch_message(giveaway["message_id"])
                except (disnake.NotFound, disnake.Forbidden):
                    message = None
        else:
            channel = message.channel

        entries = await get_entries(giveaway["id"])
        entries_count = len(entries)
        winners = random.sample(entries, min(giveaway["winners_count"], entries_count)) if entries else []

        if message:
            try:
                await message.edit(embed=build_giveaway_embed(giveaway, entries_count), view=None)
            except disnake.HTTPException:
                pass

        if not channel:
            return

        if winners:
            winners_mentions = ", ".join(f"<@{uid}>" for uid in winners)
            result_embed = Embed(
                description=(
                    f"### 🎉 Розыгрыш завершён!\n"
                    f"**Приз:** {giveaway['prize']}\n"
                    f"**Победител{'ь' if len(winners) == 1 else 'и'}:** {winners_mentions}\n\n"
                    f"Поздравляем! Свяжитесь с <@{giveaway['host_id']}> для получения приза."
                ),
                color=disnake.Color.green()
            )
            result_embed.set_footer(text="Heavenly Design © 2026")
            await channel.send(content=winners_mentions, embed=result_embed)
        else:
            no_winners_embed = Embed(
                description=(
                    f"### 😔 Розыгрыш завершён без победителей\n"
                    f"**Приз:** {giveaway['prize']}\n\n"
                    f"Никто не принял участие."
                ),
                color=disnake.Color.red()
            )
            no_winners_embed.set_footer(text="Heavenly Design © 2026")
            await channel.send(embed=no_winners_embed)

    @commands.slash_command(name="giveaway_start", description="Запустить новый розыгрыш")
    @commands.has_permissions(administrator=True)
    async def giveaway_start(
        self,
        inter: disnake.ApplicationCommandInteraction,
        prize: str = Param(description="Что разыгрывается", max_length=200),
        duration: str = Param(description=f"Длительность. {format_duration_input_hint()}"),
        winners: int = Param(default=1, description="Количество победителей", ge=1, le=20),
        required_role: disnake.Role = Param(default=None, description="Роль, обязательная для участия"),
        channel: disnake.TextChannel = Param(default=None, description="Канал для розыгрыша (по умолчанию — текущий)"),
    ):
        seconds = parse_duration(duration)
        if seconds is None:
            await inter.response.send_message(
                f"❌ Не удалось распознать длительность. {format_duration_input_hint()}", ephemeral=True
            )
            return

        target_channel = channel or inter.channel
        end_time = int(time.time()) + seconds

        giveaway_id = await create_giveaway_db(
            guild_id=inter.guild.id,
            channel_id=target_channel.id,
            host_id=inter.author.id,
            prize=prize,
            winners_count=winners,
            end_time=end_time,
            required_role_id=required_role.id if required_role else None,
        )

        giveaway = await get_giveaway(giveaway_id)
        embed = build_giveaway_embed(giveaway, 0)

        msg = await target_channel.send(embed=embed, view=GiveawayView())
        await set_giveaway_message_id(giveaway_id, msg.id)

        if target_channel.id == inter.channel.id:
            await inter.response.send_message(f"✅ Розыгрыш запущен! (ID: `{giveaway_id}`)", ephemeral=True)
        else:
            await inter.response.send_message(
                f"✅ Розыгрыш запущен в {target_channel.mention}! (ID: `{giveaway_id}`)", ephemeral=True
            )

    @commands.slash_command(name="giveaway_end", description="Завершить розыгрыш досрочно по его ID")
    @commands.has_permissions(administrator=True)
    async def giveaway_end_cmd(
        self,
        inter: disnake.ApplicationCommandInteraction,
        giveaway_id: int = Param(description="ID розыгрыша"),
    ):
        giveaway = await get_giveaway(giveaway_id)
        if not giveaway:
            await inter.response.send_message("❌ Розыгрыш с таким ID не найден.", ephemeral=True)
            return
        if giveaway["ended"]:
            await inter.response.send_message("ℹ️ Розыгрыш уже завершён.", ephemeral=True)
            return

        await inter.response.send_message(f"⏹️ Розыгрыш `{giveaway_id}` завершается…", ephemeral=True)
        await self.finish_giveaway(giveaway)

    @commands.slash_command(name="giveaway_reroll", description="Выбрать новых победителей уже завершённого розыгрыша")
    @commands.has_permissions(administrator=True)
    async def giveaway_reroll_cmd(
        self,
        inter: disnake.ApplicationCommandInteraction,
        giveaway_id: int = Param(description="ID розыгрыша"),
    ):
        giveaway = await get_giveaway(giveaway_id)
        if not giveaway:
            await inter.response.send_message("❌ Розыгрыш с таким ID не найден.", ephemeral=True)
            return
        if not giveaway["ended"]:
            await inter.response.send_message("❌ Розыгрыш ещё не завершён.", ephemeral=True)
            return

        entries = await get_entries(giveaway_id)
        if not entries:
            await inter.response.send_message("❌ Участников не было — реролл невозможен.", ephemeral=True)
            return

        winners = random.sample(entries, min(giveaway["winners_count"], len(entries)))
        winners_mentions = ", ".join(f"<@{uid}>" for uid in winners)

        await inter.response.send_message("✅ Реролл выполнен!", ephemeral=True)

        reroll_embed = Embed(
            description=(
                f"### 🔁 Реролл розыгрыша!\n"
                f"**Приз:** {giveaway['prize']}\n"
                f"**Новые победители:** {winners_mentions}\n\n"
                f"Поздравляем! 🎉"
            ),
            color=disnake.Color.gold()
        )
        reroll_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(content=winners_mentions, embed=reroll_embed)

    @commands.slash_command(name="giveaway_list", description="Показать активные розыгрыши")
    async def giveaway_list_cmd(self, inter: disnake.ApplicationCommandInteraction):
        active = await get_active_giveaways(inter.guild.id)
        if not active:
            await inter.response.send_message("ℹ️ Сейчас нет активных розыгрышей.", ephemeral=True)
            return

        embed = Embed(title="🎉 Активные розыгрыши", color=GIVEAWAY_COLOR)
        for g in active:
            count = await count_entries(g["id"])
            channel = self.bot.get_channel(g["channel_id"])
            jump = f"https://discord.com/channels/{g['guild_id']}/{g['channel_id']}/{g['message_id']}" if g["message_id"] else None
            value = (
                f"Организатор: <@{g['host_id']}>\n"
                f"Победителей: {g['winners_count']} • Участников: {count}\n"
                f"Окончание: <t:{g['end_time']}:R>"
            )
            if jump:
                value += f"\n[Перейти к розыгрышу]({jump})"
            embed.add_field(name=f"🏆 {g['prize']} (ID: {g['id']})", value=value, inline=False)

        embed.set_footer(text="Heavenly Design © 2026")
        await inter.response.send_message(embed=embed, ephemeral=True)


def setup(bot: Bot):
    bot.add_cog(Giveaway(bot))