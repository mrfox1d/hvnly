import asyncio
import aiosqlite
import disnake
from disnake.ext import commands
from disnake.ext.commands import Cog
from disnake import ui, SelectOption, Embed, ButtonStyle, TextInputStyle

TICKET_CATEGORY_ID = 1529852289874006187
ALLOWED_ROLE_IDS = {
    1529562977127108668,
    1529564459440275466,
    1529863867046559854,
}
DB_PATH = "database.db"

GOLD_EMOJI = "<:gold:1529803326898831400>"

SERVICES = {
    "avatar": {"name": "Аватарка", "price": 135},
    "banner": {"name": "Баннер", "price": 150},
    "pack":   {"name": "Аватарка + Баннер", "price": 260},
    "vk":     {"name": "Оформление VK сообщества", "price": 300},
    "custom": {"name": "Другое / Индивидуально", "price": 200},
}

DIFFICULTIES = {
    "easy":   {"name": "Простая (минимализм)", "mult": 1.0},
    "medium": {"name": "Средняя (стандарт)", "mult": 1.2},
    "hard":   {"name": "Сложная (детализированная / 3D)", "mult": 1.5},
}

CURRENCY_RATES = {
    "rub":    {"label": "Рубли (₽)", "rate": 1.0, "symbol": "₽"},
    "hryvna": {"label": "Гривны (₴)", "rate": 0.45, "symbol": "₴"},
    "gold":   {"label": "Gold Standoff 2", "rate": 1.0, "symbol": "G"},
}

REQUISITES = {
    "rub":    "Карта Сбербанк: `2200 7005 1768 0616`",
    "hryvna": "Карта ПриватБанк: `4441 1110 4526 5349`",
    "gold":   f"⚠️ Gold Standoff 2 {GOLD_EMOJI} — реквизиты выставляются автоматически через API скинов.",
}

async def init_db():
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
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        try:
            await db.execute("ALTER TABLE orders ADD COLUMN designer_id INTEGER")
        except aiosqlite.OperationalError:
            pass
        await db.commit()

async def create_order_db(channel_id: int, customer_id: int, task: str, service: str, difficulty: str, currency: str, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders (channel_id, customer_id, task, service, difficulty, currency, price, status) VALUES (?, ?, ?, ?, ?, ?, ?, 'unpaid')",
            (channel_id, customer_id, task, service, difficulty, currency, price)
        )
        await db.commit()

async def get_order_db(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT customer_id, task, service, difficulty, currency, price, status, designer_id FROM orders WHERE channel_id = ?", (channel_id,)) as cursor:
            row = await cursor.fetchone()
            if row:
                return {
                    "customer_id": row[0],
                    "task": row[1],
                    "service": row[2],
                    "difficulty": row[3],
                    "currency": row[4],
                    "price": row[5],
                    "status": row[6],
                    "designer_id": row[7]
                }
            return None

async def update_order_status_db(channel_id: int, status: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = ? WHERE channel_id = ?", (status, channel_id))
        await db.commit()

async def assign_designer_db(channel_id: int, designer_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET designer_id = ?, status = 'in_progress' WHERE channel_id = ?", (designer_id, channel_id))
        await db.commit()

async def delete_order_db(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM orders WHERE channel_id = ?", (channel_id,))
        await db.commit()

def is_staff(member: disnake.Member) -> bool:
    role_ids = {r.id for r in member.roles}
    return bool(role_ids & ALLOWED_ROLE_IDS) or member.guild_permissions.administrator


class StartButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Создать заказ", custom_id="create_order", emoji="🛒", style=ButtonStyle.primary)
    async def create_order(self, button: ui.Button, inter: disnake.MessageInteraction):
        embed = Embed(
            description=(
                "### 🎨 Шаг 1: Параметры заказа\n"
                "Выберите **тип работы**, **сложность** и **валюту оплаты**, а затем нажмите кнопку ввода ТЗ."
            )
        )
        embed.set_footer(text="Heavenly Design © 2026")

        await inter.response.send_message(
            embed=embed,
            view=OrderConfigView(),
            ephemeral=True,
        )


class OrderConfigView(ui.View):
    def __init__(self):
        super().__init__(timeout=180)
        self.selected_service = "avatar"
        self.selected_difficulty = "medium"
        self.selected_currency = "rub"

    @ui.select(
        placeholder="1. Выберите тип работы…",
        options=[
            SelectOption(label="Аватарка", value="avatar", description="От ~135 ₽", emoji="🖼️"),
            SelectOption(label="Баннер", value="banner", description="От ~150 ₽", emoji="🎨"),
            SelectOption(label="Аватарка + Баннер", value="pack", description="От ~260 ₽", emoji="📦"),
            SelectOption(label="Оформление VK", value="vk", description="От ~300 ₽", emoji="🌐"),
            SelectOption(label="Другое", value="custom", description="Индивидуальная работа", emoji="⚙️"),
        ],
        custom_id="select_service"
    )
    async def select_service(self, select: ui.Select, inter: disnake.MessageInteraction):
        self.selected_service = select.values[0]
        await inter.response.defer()

    @ui.select(
        placeholder="2. Выберите сложность…",
        options=[
            SelectOption(label="Простая", value="easy", description="Базовый арт / минимализм", emoji="⚡"),
            SelectOption(label="Средняя", value="medium", description="Стандартная детализация", emoji="🔥"),
            SelectOption(label="Сложная", value="hard", description="Высокая детализация / 3D элементы", emoji="💎"),
        ],
        custom_id="select_difficulty"
    )
    async def select_difficulty(self, select: ui.Select, inter: disnake.MessageInteraction):
        self.selected_difficulty = select.values[0]
        await inter.response.defer()

    @ui.select(
        placeholder="3. Выберите валюту…",
        options=[
            SelectOption(label="Рубли (₽)", value="rub", emoji="💳"),
            SelectOption(label="Гривны (₴)", value="hryvna", emoji="💵"),
            SelectOption(label="Gold Standoff 2", value="gold", emoji=GOLD_EMOJI),
        ],
        custom_id="select_currency"
    )
    async def select_currency(self, select: ui.Select, inter: disnake.MessageInteraction):
        self.selected_currency = select.values[0]
        await inter.response.defer()

    @ui.button(label="Далее: Указать ТЗ", style=ButtonStyle.success, emoji="✏️", row=4)
    async def confirm(self, button: ui.Button, inter: disnake.MessageInteraction):
        await inter.response.send_modal(
            modal=OrderModal(
                service=self.selected_service,
                difficulty=self.selected_difficulty,
                currency=self.selected_currency
            )
        )


class OrderModal(ui.Modal):
    def __init__(self, service: str, difficulty: str, currency: str):
        self.service = service
        self.difficulty = difficulty
        self.currency = currency

        components = [
            ui.TextInput(
                label="・Опишите ваш заказ (ТЗ):",
                custom_id="task_input",
                style=TextInputStyle.paragraph,
                placeholder="Например: Аватарка в стиле аниме, цвета: синий и чёрный…",
                min_length=10,
                max_length=1000,
                required=True,
            )
        ]
        super().__init__(title="📋 Техническое задание", custom_id="order_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        task = inter.text_values["task_input"]

        await inter.response.send_message(
            embed=Embed(description="⏳ Создаём тикет и рассчитываем стоимость…").set_footer(text="Heavenly Design © 2026"),
            ephemeral=True,
        )

        base_price = SERVICES[self.service]["price"]
        mult = DIFFICULTIES[self.difficulty]["mult"]
        rate = CURRENCY_RATES[self.currency]["rate"]
        symbol = GOLD_EMOJI if self.currency == "gold" else CURRENCY_RATES[self.currency]["symbol"]

        final_price = int(round((base_price * mult) * rate))

        guild = inter.guild
        customer = inter.author
        category = guild.get_channel(TICKET_CATEGORY_ID)

        overwrites = {
            guild.default_role: disnake.PermissionOverwrite(view_channel=False),
            customer:           disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True),
        }
        for role in guild.roles:
            if role.id in ALLOWED_ROLE_IDS:
                overwrites[role] = disnake.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)

        try:
            ticket_channel = await guild.create_text_channel(
                name=f"🛒・{customer.display_name}",
                category=category,
                overwrites=overwrites,
                reason=f"Заказ от {customer}",
            )
        except Exception as e:
            await inter.edit_original_response(
                embed=Embed(description=f"❌ Не удалось создать тикет: `{e}`").set_footer(text="Heavenly Design © 2026"),
            )
            return

        await create_order_db(
            channel_id=ticket_channel.id,
            customer_id=customer.id,
            task=task,
            service=SERVICES[self.service]['name'],
            difficulty=DIFFICULTIES[self.difficulty]['name'],
            currency=CURRENCY_RATES[self.currency]['label'],
            price=final_price
        )

        ticket_embed = Embed(
            description=(
                f"### 🎨 Новый заказ\n"
                f"**Заказчик:** {customer.mention}\n\n"
                f"**⚙️ Детали заказа:**\n"
                f"・Услуга: **{SERVICES[self.service]['name']}**\n"
                f"・Сложность: **{DIFFICULTIES[self.difficulty]['name']}**\n"
                f"・Валюта: **{CURRENCY_RATES[self.currency]['label']}**\n\n"
                f"**📝 Техническое задание:**\n{task}\n\n"
                f"**💰 Рассчитанная стоимость:** `{final_price}` {symbol}\n\n"
                f"**📦 Реквизиты для оплаты:**\n{REQUISITES[self.currency]}\n\n"
                "-# После оплаты нажмите «Оплата получена» (выполняется администрацией)."
            )
        )
        ticket_embed.set_author(name=guild.name, icon_url=guild.icon.url)
        ticket_embed.set_footer(text="Heavenly Design © 2026")

        await ticket_channel.send(
            content=f"{customer.mention} | 🛒 Тикет создан!",
            embed=ticket_embed,
            view=TicketControlView(),
        )

        done_embed = Embed(
            description=(
                f"### ✅ Тикет создан!\n"
                f"Перейдите в канал {ticket_channel.mention} — там указаны подробности заказа и реквизиты.\n\n"
                "-# Как оплатите, сообщите администратору в тикете."
            )
        )
        done_embed.set_footer(text="Heavenly Design © 2026")
        await inter.edit_original_response(embed=done_embed)


class TicketControlView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="✋ Взяться за заказ", custom_id="take_order", style=ButtonStyle.primary)
    async def take_order(self, button: ui.Button, inter: disnake.MessageInteraction):
        if not is_staff(inter.author):
            await inter.response.send_message("❌ У вас нет прав для взятия заказа.", ephemeral=True)
            return

        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        if order.get("designer_id"):
            await inter.response.send_message("❌ За этот заказ уже взялся другой дизайнер.", ephemeral=True)
            return

        await assign_designer_db(inter.channel.id, inter.author.id)

        button.disabled = True
        button.label = f"Дизайнер: {inter.author.display_name}"
        button.style = ButtonStyle.secondary

        await inter.response.edit_message(view=self)

        designer_embed = Embed(
            description=(
                f"🎨 **Дизайнер {inter.author.mention} взял ваш заказ в работу!**\n"
                f"Вы можете обсудить с ним детали напрямую в этом тикете."
            )
        )
        designer_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(embed=designer_embed)

    @ui.button(label="✅ Оплата получена", custom_id="payment_received", style=ButtonStyle.success)
    async def payment_received(self, button: ui.Button, inter: disnake.MessageInteraction):
        if not is_staff(inter.author):
            await inter.response.send_message("❌ Только администрация может подтвердить оплату.", ephemeral=True)
            return

        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        if order["status"] == "paid":
            await inter.response.send_message("ℹ️ Оплата уже была подтверждена.", ephemeral=True)
            return

        await update_order_status_db(inter.channel.id, "paid")

        button.disabled = True
        button.label = "✅ Оплата подтверждена"

        for item in self.children:
            if getattr(item, "custom_id", None) == "close_ticket":
                item.disabled = False

        await inter.response.edit_message(view=self)

        confirm_embed = Embed(
            description=(
                "### 💳 Оплата подтверждена!\n"
                f"Подтвердил: {inter.author.mention}\n\n"
                "-# Дизайнер приступит к работе в ближайшее время."
            )
        )
        confirm_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(embed=confirm_embed)

    @ui.button(label="🔒 Завершить заказ", custom_id="close_ticket", style=ButtonStyle.danger, disabled=True)
    async def close_ticket(self, button: ui.Button, inter: disnake.MessageInteraction):
        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        is_customer = inter.author.id == order["customer_id"]
        if not is_customer and not is_staff(inter.author):
            await inter.response.send_message("❌ Только заказчик или администрация может закрыть тикет.", ephemeral=True)
            return

        if order["status"] != "paid" and order["status"] != "in_progress":
            await inter.response.send_message("❌ Тикет можно закрыть только после подтверждения оплаты.", ephemeral=True)
            return

        await inter.response.send_message(
            embed=Embed(description="⚠️ Вы уверены, что хотите завершить заказ и закрыть тикет?").set_footer(text="Heavenly Design © 2026"),
            view=ConfirmCloseView(customer_id=order["customer_id"], order_data=order),
            ephemeral=True,
        )


class ConfirmCloseView(ui.View):
    def __init__(self, customer_id: int, order_data: dict):
        super().__init__(timeout=60)
        self.customer_id = customer_id
        self.order_data = order_data

    @ui.button(label="Да, завершить", style=ButtonStyle.danger, emoji="🔒")
    async def confirm(self, button: ui.Button, inter: disnake.MessageInteraction):
        if inter.author.id != self.customer_id and not is_staff(inter.author):
            await inter.response.send_message("❌ Недостаточно прав.", ephemeral=True)
            return

        await inter.response.send_modal(modal=ReviewModal(order_data=self.order_data))

    @ui.button(label="Отмена", style=ButtonStyle.secondary, emoji="↩️")
    async def cancel(self, button: ui.Button, inter: disnake.MessageInteraction):
        await inter.response.edit_message(
            embed=Embed(description="↩️ Закрытие отменено.").set_footer(text="Heavenly Design © 2026"),
            view=None,
        )


class ReviewModal(ui.Modal):
    def __init__(self, order_data: dict):
        self.order_data = order_data
        components = [
            ui.TextInput(
                label="・Оценка работы (от 1 до 5 ⭐):",
                custom_id="stars_input",
                style=TextInputStyle.short,
                placeholder="5",
                min_length=1,
                max_length=1,
                required=True,
            ),
            ui.TextInput(
                label="・Ваш отзыв:",
                custom_id="review_input",
                style=TextInputStyle.paragraph,
                placeholder="Напишите впечатления о работе с дизайнером...",
                min_length=5,
                max_length=1000,
                required=False,
            )
        ]
        super().__init__(title="⭐ Оставить отзыв", custom_id="review_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        stars_raw = inter.text_values["stars_input"]
        review_text = inter.text_values["review_input"] or "Без комментариев."

        try:
            stars_cnt = int(stars_raw)
            stars_cnt = max(1, min(5, stars_cnt))
        except ValueError:
            stars_cnt = 5

        stars_str = "⭐" * stars_cnt
        designer_mention = f"<@{self.order_data['designer_id']}>" if self.order_data.get("designer_id") else "Не назначен"

        reviews_channel = inter.guild.get_channel(1529563365708660947)
        if reviews_channel:
            rev_embed = Embed(
                description=(
                    f"### ⭐ Новый отзыв!\n"
                    f"**Заказчик:** {inter.author.mention}\n"
                    f"**Дизайнер:** {designer_mention}\n\n"
                    f"**⚙️ Информация о заказе:**\n"
                    f"・Услуга: **{self.order_data['service']}**\n"
                    f"・Сложность: **{self.order_data['difficulty']}**\n"
                    f"・Стоимость: **{self.order_data['price']}** ({self.order_data['currency']})\n\n"
                    f"**Оценка:** {stars_str}\n"
                    f"**💬 Комментарий:**\n{review_text}"
                )
            )
            rev_embed.set_author(name=inter.guild.name, icon_url=inter.guild.icon.url)
            rev_embed.set_footer(text="Heavenly Design © 2026")
            await reviews_channel.send(embed=rev_embed)

        await inter.response.send_message(
            embed=Embed(description="🎉 Спасибо за отзыв! Канал будет удалён через 5 секунд.").set_footer(text="Heavenly Design © 2026"),
            ephemeral=True,
        )

        close_embed = Embed(
            description=(
                "### 🎉 Заказ завершён!\n"
                "Спасибо за обращение в **Heavenly Design**!\n\n"
                "-# Канал будет удалён через 5 секунд."
            )
        )
        close_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(embed=close_embed)

        await delete_order_db(inter.channel.id)
        await asyncio.sleep(5)
        try:
            await inter.channel.delete(reason="Заказ завершён")
        except disnake.NotFound:
            pass


class Order(Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @Cog.listener()
    async def on_ready(self):
        await init_db()
        self.bot.add_view(StartButton())
        self.bot.add_view(TicketControlView())

    @commands.command(name="panel")
    async def panel(self, ctx: commands.Context):
        file = disnake.File("banner.jpg", filename="banner.jpg")

        embed = Embed(
            title="✨ HEAVENLY DESIGN — ЗАКАЗ УСЛУГ",
            description=(
                "Добро пожаловать в нашу студию дизайна!\n"
                "Воспользуйтесь меню ниже, чтобы быстро оформить заявку.\n\n"
                "### 📋 **Процесс оформления заказа:**\n"
                "**1.** Выберите **тип работы**, **сложность** и **валюту**\n"
                "**2.** Заполните подробное **ТЗ** во всплывающем окне\n"
                "**3.** Бот автоматически создаст ваш **личный тикет**"
            ),
            color=disnake.Color.from_rgb(114, 137, 218)
        )

        embed.add_field(
            name="💳 Способы оплаты",
            value="```RUB (₽) | UAH (₴) | Gold```",
            inline=False
        )

        embed.set_image(url="attachment://banner.jpg")

        embed.set_footer(
            text="Heavenly Design © 2026 • Быстро, качественно, надежно",
            icon_url=ctx.bot.user.display_avatar.url
        )

        await ctx.message.delete()
        await ctx.send(file=file, embed=embed, view=StartButton())


def setup(bot: commands.Bot):
    bot.add_cog(Order(bot))