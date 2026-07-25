import asyncio
import re
import time
from collections import defaultdict
import aiosqlite
import disnake
from disnake.ext.commands import Bot, Cog, command, slash_command, has_permissions, errors, Param

DB_PATH = "database.db"
LOG_CHANNEL_ID = 1530086386173087774

COLOR_MAIN = 0x2B2D31
COLOR_ERROR = disnake.Color.brand_red()
COLOR_SUCCESS = disnake.Color.green()

URL_REGEX = re.compile(r"(https?://[^\s]+|www\.[^\s]+|[a-zA-Z0-9-]+\.[a-zA-Z]{2,}(?:/[^\s]*)?)", re.IGNORECASE)
# Регулярка для точного подсчёта ВСЕХ тегов (включая повторы и роли)
MENTION_REGEX = re.compile(r"<@!?\d+>|<@&\d+>|@everyone|@here")


def get_warning_ending(count: int) -> str:
    if 11 <= count % 100 <= 14:
        return "й"
    last_digit = count % 10
    if last_digit == 1:
        return "е"
    if 2 <= last_digit <= 4:
        return "я"
    return "й"

async def give_warning(user_id: int, reason: str = None):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO warnings (user_id, warnings) VALUES (?, 1)
            ON CONFLICT(user_id) DO UPDATE SET warnings = warnings + 1
        """, (user_id,))
        await db.commit()


async def remove_warning(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            UPDATE warnings 
            SET warnings = CASE WHEN warnings > 0 THEN warnings - 1 ELSE 0 END 
            WHERE user_id = ?
        """, (user_id,))
        await db.commit()


async def get_warnings(user_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT warnings FROM warnings WHERE user_id = ?", (user_id,)) as cursor:
            return await cursor.fetchone()


async def get_all_settings() -> dict:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT key, value FROM settings") as cursor:
            rows = await cursor.fetchall()
            defaults = {"links": True, "spam": True, "caps": True, "massmention": True}
            for key, val in rows:
                defaults[key] = bool(val)
            return defaults


async def set_setting(key: str, value: bool):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, int(value)))
        await db.commit()


async def send_log(bot: Bot, embed: disnake.Embed):
    channel = bot.get_channel(LOG_CHANNEL_ID)
    if not channel:
        try:
            channel = await bot.fetch_channel(LOG_CHANNEL_ID)
        except Exception:
            return
    if channel:
        try:
            await channel.send(embed=embed)
        except disnake.HTTPException:
            pass


class SettingsView(disnake.ui.View):
    def __init__(self, settings_data: dict, bot: Bot):
        super().__init__(timeout=180)
        self.settings = settings_data
        self.bot = bot
        self._build_buttons()

    def _build_buttons(self):
        self.clear_items()
        modules = [
            ("links", "Фильтр ссылок", "🔗"),
            ("spam", "Анти-спам", "⚡"),
            ("caps", "Анти-капс", "🔤"),
            ("massmention", "Масс-теги", "🏷️")
        ]
        for key, label, emoji in modules:
            enabled = self.settings.get(key, True)
            btn = disnake.ui.Button(
                label=f"{label}: {'ВКЛ' if enabled else 'ВЫКЛ'}",
                style=disnake.ButtonStyle.success if enabled else disnake.ButtonStyle.danger,
                custom_id=f"btn_{key}",
                emoji=emoji
            )
            btn.callback = self._make_callback(key)
            self.add_item(btn)

    def _make_callback(self, key: str):
        async def callback(inter: disnake.MessageInteraction):
            if not inter.author.guild_permissions.administrator:
                await inter.response.send_message("❌ Недостаточно прав.", ephemeral=True)
                return
            new_val = not self.settings.get(key, True)
            self.settings[key] = new_val
            await set_setting(key, new_val)
            self._build_buttons()
            await inter.response.edit_message(view=self)

            log_embed = disnake.Embed(
                title="⚙️ Изменение настроек защиты",
                description=f"Администратор {inter.author.mention} изменил модуль **{key}** на `{ 'ВКЛ' if new_val else 'ВЫКЛ' }`.",
                color=COLOR_MAIN
            )
            log_embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
            await send_log(self.bot, log_embed)

        return callback


class RemoveWarningView(disnake.ui.View):
    def __init__(self, target_id: int):
        super().__init__(timeout=86400)
        self.target_id = target_id

    @disnake.ui.button(label="Снять предупреждение", style=disnake.ButtonStyle.danger, emoji="🗑️")
    async def unwarn(self, button: disnake.ui.Button, inter: disnake.MessageInteraction):
        if not inter.author.guild_permissions.administrator:
            await inter.response.send_message("❌ Только администраторы могут снимать предупреждения.", ephemeral=True)
            return

        await remove_warning(self.target_id)
        button.disabled = True
        button.label = "Предупреждение снято"
        button.style = disnake.ButtonStyle.secondary
        await inter.response.edit_message(view=self)
        
        data = await get_warnings(self.target_id)
        count = data[0] if data else 0
        
        await inter.followup.send(
            f"✅ Администратор {inter.author.mention} снял предупреждение с пользователя <@{self.target_id}>. Осталось варнов: `{count}`.",
            ephemeral=False
        )

        log_embed = disnake.Embed(
            title="🗑️ Снятие предупреждения",
            description=f"**Администратор:** {inter.author.mention}\n**Пользователь:** <@{self.target_id}>\n**Осталось варнов:** `{count}`",
            color=COLOR_SUCCESS
        )
        log_embed.set_footer(text="Heavenly Design © 2026", icon_url=inter.bot.user.display_avatar.url)
        await send_log(inter.bot, log_embed)


class Commands(Cog):
    def __init__(self, bot: Bot):
        self.bot = bot
        self.spam_cache = defaultdict(list)

    async def _check_automod(self, message: disnake.Message) -> bool:
        """Проверка сообщения на нарушения. Возвращает True, если было найдено нарушение."""
        if message.author.bot or not message.guild:
            return False
        if message.author.guild_permissions.administrator:
            return False

        settings = await get_all_settings()

        # 1. Спам
        if settings.get("spam", True):
            now = time.time()
            user_msgs = [t for t in self.spam_cache[message.author.id] if now - t <= 2.0]
            user_msgs.append(now)
            self.spam_cache[message.author.id] = user_msgs

            if len(user_msgs) >= 5:
                self.spam_cache[message.author.id] = []
                try:
                    await message.delete()
                except disnake.HTTPException:
                    pass
                await self._trigger_automod(message, "Спам (5+ сообщений за 2 сек)")
                return True

        # 2. Массовые упоминания (исправлено через регулярку)
        if settings.get("massmention", True):
            mentions_count = len(MENTION_REGEX.findall(message.content))
            if mentions_count >= 6:
                try:
                    await message.delete()
                except disnake.HTTPException:
                    pass
                await self._trigger_automod(message, f"Массовые упоминания ({mentions_count} тегов)")
                return True

        # 3. Капс
        if settings.get("caps", True):
            letters = [c for c in message.content if c.isalpha()]
            if len(letters) >= 6:
                upper_count = sum(1 for c in letters if c.isupper())
                ratio = upper_count / len(letters)
                if ratio >= 0.90:
                    try:
                        await message.delete()
                    except disnake.HTTPException:
                        pass
                    await self._trigger_automod(message, f"Злоупотребление капсом ({int(ratio * 100)}%)")
                    return True

        # 4. Запрещённые ссылки
        if settings.get("links", True):
            urls = URL_REGEX.findall(message.content)
            if urls:
                has_forbidden = any("shitcode.pw" not in url.lower() for url in urls)
                if has_forbidden:
                    try:
                        await message.delete()
                    except disnake.HTTPException:
                        pass
                    await self._trigger_automod(message, "Отправка запрещённых ссылок")
                    return True

        return False

    @Cog.listener()
    async def on_message(self, message: disnake.Message):
        await self._check_automod(message)

    @Cog.listener()
    async def on_message_delete(self, message: disnake.Message):
        if message.author.bot or not message.guild:
            return

        content = message.content if message.content else "*Сообщение не содержало текста (вложения/эмбед)*"
        if len(content) > 1024:
            content = content[:1021] + "..."

        embed = disnake.Embed(
            title="🗑️ Сообщение удалено",
            color=COLOR_ERROR
        )
        embed.add_field(name="Автор", value=f"{message.author.mention} (`{message.author.id}`)", inline=True)
        embed.add_field(name="Канал", value=message.channel.mention, inline=True)
        embed.add_field(name="Содержимое", value=content, inline=False)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)

        await send_log(self.bot, embed)

    @Cog.listener()
    async def on_message_edit(self, before: disnake.Message, after: disnake.Message):
        if after.author.bot or not after.guild:
            return
        if before.content == after.content:
            return

        # Сначала проверяем изменённое сообщение на нарушения
        violated = await self._check_automod(after)
        if violated:
            return  # Если было нарушение, сообщение удалено и залогировано автомодерацией

        # Логируем обычное изменение сообщения
        before_text = before.content if before.content else "*Пусто*"
        after_text = after.content if after.content else "*Пусто*"

        if len(before_text) > 1024:
            before_text = before_text[:1021] + "..."
        if len(after_text) > 1024:
            after_text = after_text[:1021] + "..."

        embed = disnake.Embed(
            title="✏️ Сообщение отредактировано",
            color=COLOR_MAIN
        )
        embed.add_field(name="Автор", value=f"{after.author.mention} (`{after.author.id}`)", inline=True)
        embed.add_field(name="Канал", value=after.channel.mention, inline=True)
        embed.add_field(name="Перейти", value=f"[Перейти к сообщению]({after.jump_url})", inline=False)
        embed.add_field(name="До", value=before_text, inline=False)
        embed.add_field(name="После", value=after_text, inline=False)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)

        await send_log(self.bot, embed)

    async def _trigger_automod(self, message: disnake.Message, reason: str):
        await give_warning(message.author.id, reason)
        data = await get_warnings(message.author.id)
        current_warns = data[0] if data else 1

        embed = disnake.Embed(
            title="🛡️ Автомодерация",
            description=f"Пользователь {message.author.mention} получил предупреждение.\n**Причина:** `{reason}`",
            color=COLOR_ERROR
        )
        embed.add_field(name="📊 Всего варнов", value=f"`{current_warns}/3`", inline=True)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)

        await message.channel.send(embed=embed, view=RemoveWarningView(message.author.id))

        log_embed = disnake.Embed(
            title="🚨 Срабатывание Автомодерации",
            description=(
                f"**Нарушитель:** {message.author.mention} (`{message.author.id}`)\n"
                f"**Канал:** {message.channel.mention}\n"
                f"**Причина:** {reason}\n"
                f"**Варны:** `{current_warns}/3`"
            ),
            color=COLOR_ERROR
        )
        log_embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await send_log(self.bot, log_embed)

        if current_warns >= 3:
            try:
                await message.guild.ban(message.author, reason="Превышен лимит предупреждений (3/3)")
            except disnake.HTTPException:
                pass

    @Cog.listener()
    async def on_command_error(self, ctx, error):
        if isinstance(error, errors.MissingPermissions):
            embed = disnake.Embed(
                title="❌ Ошибка доступа",
                description="У вас недостаточно прав для использования этой команды.",
                color=COLOR_ERROR
            )
            embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
            await ctx.send(embed=embed, delete_after=5)

    @Cog.listener()
    async def on_slash_command_error(self, inter: disnake.ApplicationCommandInteraction, error):
        if isinstance(error, errors.MissingPermissions):
            embed = disnake.Embed(
                title="❌ Ошибка доступа",
                description="У вас недостаточно прав для использования этой команды.",
                color=COLOR_ERROR
            )
            embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
            if inter.response.is_done():
                await inter.followup.send(embed=embed, ephemeral=True)
            else:
                await inter.response.send_message(embed=embed, ephemeral=True)

    @command(name="settings", aliases=["настройки", "защита"])
    @has_permissions(administrator=True)
    async def settings_cmd(self, ctx):
        await self._process_settings(ctx)

    @slash_command(name="settings", description="Управление модулями защиты сервера")
    @has_permissions(administrator=True)
    async def slash_settings(self, inter: disnake.ApplicationCommandInteraction):
        await inter.response.defer(ephemeral=True)
        await self._process_settings(inter)

    async def _process_settings(self, target_ctx):
        settings_data = await get_all_settings()
        embed = disnake.Embed(
            title="⚙️ Панель управления защитой",
            description="Нажимайте на кнопки ниже, чтобы включать или отключать модули автомодерации:",
            color=COLOR_MAIN
        )
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        view = SettingsView(settings_data, self.bot)

        if isinstance(target_ctx, disnake.ApplicationCommandInteraction):
            await target_ctx.followup.send(embed=embed, view=view, ephemeral=True)
        else:
            await target_ctx.send(embed=embed, view=view)

    @command(name="warn", aliases=["пред", "варн"])
    @has_permissions(administrator=True)
    async def warn(self, ctx, user: disnake.User, *, reason: str = "Не указана"):
        await self._process_warn(ctx, user, reason)

    @slash_command(name="warn", description="Выдать предупреждение пользователю")
    @has_permissions(administrator=True)
    async def slash_warn(self, inter: disnake.ApplicationCommandInteraction, user: disnake.User, reason: str = "Не указана"):
        await inter.response.defer()
        await self._process_warn(inter, user, reason)

    async def _process_warn(self, target_ctx, user: disnake.User, reason: str):
        await give_warning(user.id, reason)
        data = await get_warnings(user.id)
        current_warns = data[0] if data else 1

        if current_warns >= 3:
            try:
                guild = target_ctx.guild
                await guild.ban(user, reason="Превышен лимит предупреждений (3/3)")
            except disnake.HTTPException:
                pass

            embed = disnake.Embed(
                title="⛔ Блокировка пользователя",
                description=f"Пользователь {user.mention} набрал **3/3** предупреждений и был забанен.\n\n**Последняя причина:** {reason}",
                color=COLOR_ERROR
            )
            embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
            
            if isinstance(target_ctx, disnake.ApplicationCommandInteraction):
                await target_ctx.followup.send(embed=embed)
            else:
                await target_ctx.send(embed=embed)
            return

        author = target_ctx.author
        embed = disnake.Embed(
            title="⚠️ Выдано предупреждение",
            description=f"Модератор {author.mention} выдал предупреждение пользователю {user.mention}.",
            color=COLOR_ERROR
        )
        embed.add_field(name="📝 Причина", value=f"```{reason}```", inline=False)
        embed.add_field(name="📊 Всего варнов", value=f"`{current_warns}/3`", inline=True)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)

        if isinstance(target_ctx, disnake.ApplicationCommandInteraction):
            await target_ctx.followup.send(embed=embed, view=RemoveWarningView(user.id))
        else:
            await target_ctx.send(embed=embed, view=RemoveWarningView(user.id))

        log_embed = disnake.Embed(
            title="⚠️ Ручная выдача предупреждения",
            description=f"**Модератор:** {author.mention}\n**Нарушитель:** {user.mention}\n**Причина:** {reason}\n**Всего варнов:** `{current_warns}/3`",
            color=COLOR_ERROR
        )
        log_embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await send_log(self.bot, log_embed)

    @command(name="warnings", aliases=["предупреждения", "варны"])
    async def warnings(self, ctx, user: disnake.User = None):
        await self._process_warnings(ctx, user or ctx.author)

    @slash_command(name="warnings", description="Посмотреть предупреждения пользователя")
    async def slash_warnings(self, inter: disnake.ApplicationCommandInteraction, user: disnake.User = None):
        await inter.response.defer()
        await self._process_warnings(inter, user or inter.author)

    async def _process_warnings(self, target_ctx, target: disnake.User):
        data = await get_warnings(target.id)
        count = data[0] if data else 0
        ending = get_warning_ending(count)

        embed = disnake.Embed(
            title="📜 Учёт нарушений",
            description=f"Информация о предупреждениях пользователя {target.mention}:",
            color=COLOR_MAIN
        )
        embed.add_field(name="Текущий счётчик", value=f"**{count}** предупреждени{ending} `({count}/3)`", inline=False)
        embed.set_thumbnail(url=target.display_avatar.url)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)

        if isinstance(target_ctx, disnake.ApplicationCommandInteraction):
            await target_ctx.followup.send(embed=embed)
        else:
            await target_ctx.send(embed=embed)

    @command(name="ban", aliases=["бан"])
    @has_permissions(ban_members=True)
    async def ban(self, ctx, user: disnake.User, *, reason: str = "Не указана"):
        await self._process_ban(ctx, user, reason)

    @slash_command(name="ban", description="Забанить пользователя на сервере")
    @has_permissions(ban_members=True)
    async def slash_ban(self, inter: disnake.ApplicationCommandInteraction, user: disnake.User, reason: str = "Не указана"):
        await inter.response.defer()
        await self._process_ban(inter, user, reason)

    async def _process_ban(self, target_ctx, user: disnake.User, reason: str):
        try:
            await target_ctx.guild.ban(user, reason=f"{reason} | Выдал: {target_ctx.author}")
        except disnake.HTTPException:
            err_embed = disnake.Embed(
                title="❌ Ошибка",
                description=f"Не удалось забанить пользователя {user.mention}. Проверьте иерархию ролей.",
                color=COLOR_ERROR
            )
            if isinstance(target_ctx, disnake.ApplicationCommandInteraction):
                await target_ctx.followup.send(embed=err_embed, ephemeral=True)
            else:
                await target_ctx.send(embed=err_embed)
            return

        embed = disnake.Embed(
            title="🔨 Блокировка аккаунта",
            description=f"Модератор {target_ctx.author.mention} забанил пользователя {user.mention}.",
            color=COLOR_ERROR
        )
        embed.add_field(name="📝 Причина", value=f"```{reason}```", inline=False)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)

        if isinstance(target_ctx, disnake.ApplicationCommandInteraction):
            await target_ctx.followup.send(embed=embed)
        else:
            await target_ctx.send(embed=embed)

        log_embed = disnake.Embed(
            title="🔨 Блокировка пользователя",
            description=f"**Модератор:** {target_ctx.author.mention}\n**Забанен:** {user.mention}\n**Причина:** {reason}",
            color=COLOR_ERROR
        )
        log_embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await send_log(self.bot, log_embed)

    @command(name="clear", aliases=["очистить", "purge"])
    @has_permissions(manage_messages=True)
    async def clear(self, ctx, amount: int = 1):
        deleted = await ctx.channel.purge(limit=amount + 1)
        count = len(deleted) - 1
        embed = disnake.Embed(description=f"🧹 Удалено сообщений: **{count}**", color=COLOR_SUCCESS)
        await ctx.send(embed=embed, delete_after=3)

        log_embed = disnake.Embed(
            title="🧹 Очистка чата",
            description=f"**Модератор:** {ctx.author.mention}\n**Канал:** {ctx.channel.mention}\n**Удалено сообщений:** `{count}`",
            color=COLOR_SUCCESS
        )
        log_embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await send_log(self.bot, log_embed)

    @slash_command(name="clear", description="Очистить чат от сообщений")
    @has_permissions(manage_messages=True)
    async def slash_clear(self, inter: disnake.ApplicationCommandInteraction, amount: int = 1):
        await inter.response.defer(ephemeral=True)
        deleted = await inter.channel.purge(limit=amount)
        count = len(deleted)
        embed = disnake.Embed(description=f"🧹 Удалено сообщений: **{count}**", color=COLOR_SUCCESS)
        await inter.followup.send(embed=embed, ephemeral=True)

        log_embed = disnake.Embed(
            title="🧹 Очистка чата",
            description=f"**Модератор:** {inter.author.mention}\n**Канал:** {inter.channel.mention}\n**Удалено сообщений:** `{count}`",
            color=COLOR_SUCCESS
        )
        log_embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await send_log(self.bot, log_embed)

    @command(name="embed", aliases=["say", "объявление", "эмбед"])
    @has_permissions(administrator=True)
    async def embed(self, ctx, *, text: str):
        try:
            await ctx.message.delete()
        except disnake.HTTPException:
            pass
        await self._send_embed(ctx.channel, text)

    @slash_command(name="embed", description="Отправить объявление в формате Embed")
    @has_permissions(administrator=True)
    async def slash_embed(self, inter: disnake.ApplicationCommandInteraction, text: str):
        await self._send_embed(inter.channel, text)
        await inter.response.send_message("✅ Объявление отправлено!", ephemeral=True)

    async def _send_embed(self, channel, text: str):
        embed = disnake.Embed(description=text, color=COLOR_MAIN)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await channel.send(embed=embed)

    @command(name="sayping", aliases=["embedping", "saytag", "пинг"])
    @has_permissions(administrator=True)
    async def sayping(self, ctx, target: disnake.User | disnake.Role, *, text: str):
        try:
            await ctx.message.delete()
        except disnake.HTTPException:
            pass
        await self._send_sayping(ctx.channel, target, text)

    @slash_command(name="sayping", description="Отправить объявление с пингом роли или пользователя")
    @has_permissions(administrator=True)
    async def slash_sayping(self, inter: disnake.ApplicationCommandInteraction, target: disnake.User | disnake.Role, text: str):
        await self._send_sayping(inter.channel, target, text)
        await inter.response.send_message("✅ Объявление отправлено!", ephemeral=True)

    async def _send_sayping(self, channel, target, text: str):
        embed = disnake.Embed(description=text, color=COLOR_MAIN)
        embed.set_footer(text="Heavenly Design © 2026", icon_url=self.bot.user.display_avatar.url)
        await channel.send(content=target.mention, embed=embed)

    @slash_command(name="pf", description="Добавить работу в своё портфолио (только для Pharos'а)")
    async def portfolio_add(
        self,
        inter: disnake.ApplicationCommandInteraction,
        attachment: disnake.Attachment,
        description: str = Param(description="Краткое описание работы", max_length=500),
    ):
        if inter.author.id != 1160681372252393492:
            await inter.response.send_message("❌ Эта команда доступна только Главному Дизайнеру.", ephemeral=True)
            return
        
        showcase_channel = inter.guild.get_channel(1530600614864883774)
        if showcase_channel:
            try:
                pharos = await inter.author()
                embed = disnake.Embed(
                    title = "🎨 Новая работа от Гл. Дизайнера!",
                    description = f"**Наш главный дизайнер {pharos.mention} сделал новую работу!**\n\n**Описание:** {description}",
                    color = disnake.Color.green()
                )
                embed.set_image(url=attachment.url)
                msg = await showcase_channel.send(embed=embed)

            except disnake.HTTPException:
                pass

def setup(bot: Bot):
    bot.add_cog(Commands(bot))