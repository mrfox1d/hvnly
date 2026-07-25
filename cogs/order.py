import asyncio
import aiosqlite
import disnake
from disnake.ext import commands, tasks
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
    "avatar": {"name": "Аватарка"},
    "banner": {"name": "Баннер"},
    "pack":   {"name": "Аватарка + Баннер"},
    "vk":     {"name": "Оформление VK сообщества"},
    "custom": {"name": "Другое / Индивидуально"},
}

DIFFICULTIES = {
    "easy":   {"name": "Простая (минимализм)"},
    "medium": {"name": "Средняя (стандарт)"},
    "hard":   {"name": "Сложная (детализированная / 3D)"},
}

CURRENCY_RATES = {
    "rub":    {"label": "Рубли (₽)", "symbol": "₽"},
    "hryvna": {"label": "Гривны (₴)", "symbol": "₴"},
    "gold":   {"label": "Gold Standoff 2", "symbol": GOLD_EMOJI},
}

REQUISITES = {
    "rub":    "Карта Сбербанк: `2200 7005 1768 0616`",
    "hryvna": "Карта ПриватБанк: `4441 1110 4526 5349`",
    "gold":   f"⚠️ Gold Standoff 2 {GOLD_EMOJI} — реквизиты выставляются автоматически через API скинов.",
}


async def create_order_db(channel_id: int, customer_id: int, task: str, service: str, difficulty: str, currency: str):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            "INSERT INTO orders (channel_id, customer_id, task, service, difficulty, currency, price, status) VALUES (?, ?, ?, ?, ?, ?, NULL, 'unpaid')",
            (channel_id, customer_id, task, service, difficulty, currency)
        )
        await db.commit()


async def get_order_db(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT customer_id, task, service, difficulty, currency, price, status, designer_id, work_done_at FROM orders WHERE channel_id = ?", (channel_id,)) as cursor:
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
                    "designer_id": row[7],
                    "work_done_at": row[8]
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


async def set_price_db(channel_id: int, price: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET price = ? WHERE channel_id = ?", (price, channel_id))
        await db.commit()


async def mark_work_done_db(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE orders SET status = 'work_done', work_done_at = CURRENT_TIMESTAMP WHERE channel_id = ?", (channel_id,))
        await db.commit()


async def get_expired_orders_db():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("""
            SELECT channel_id, customer_id, service, difficulty, currency, price, designer_id 
            FROM orders 
            WHERE status = 'work_done' 
              AND work_done_at IS NOT NULL 
              AND (strftime('%s', 'now') - strftime('%s', work_done_at)) >= 259200
        """) as cursor:
            return await cursor.fetchall()


async def delete_order_db(channel_id: int):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("DELETE FROM orders WHERE channel_id = ?", (channel_id,))
        await db.commit()


def is_staff(member: disnake.Member) -> bool:
    role_ids = {r.id for r in member.roles}
    return bool(role_ids & ALLOWED_ROLE_IDS) or member.guild_permissions.administrator


def format_price(price, currency_key: str) -> str:
    if price is None:
        return "уточняется у дизайнера"
    symbol = CURRENCY_RATES.get(currency_key, {}).get("symbol", "")
    return f"{price} {symbol}".strip()


async def _credit_review_to_designer(designer_id: int, client_id: int, rating: int, comment: str):
    """Начисляет отзыв дизайнеру в базу portfolio.py (рейтинг в /profile).
    Пробует относительный импорт (если order.py и portfolio.py лежат в одном
    пакете cogs) и абсолютный (если portfolio.py доступен как отдельный модуль).
    Ошибки логируются в консоль, а не проглатываются молча."""
    add_review_fn = None
    try:
        from .portfolio import add_review as add_review_fn  # type: ignore
    except ImportError:
        try:
            from portfolio import add_review as add_review_fn  # type: ignore
        except ImportError as e:
            print(f"[Order] Не удалось импортировать add_review из portfolio.py: {e}")
            return

    try:
        await add_review_fn(designer_id, client_id, rating, comment)
    except Exception as e:
        print(f"[Order] Ошибка при начислении отзыва дизайнеру {designer_id}: {e}")


class StartButton(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Создать заказ", custom_id="create_order", emoji="🛒", style=ButtonStyle.primary)
    async def create_order(self, button: ui.Button, inter: disnake.MessageInteraction):
        embed = Embed(
            description=(
                "### 🎨 Шаг 1: Параметры заказа\n"
                "Выберите **тип работы**, **сложность** и **валюту оплаты**, а затем нажмите кнопку ввода ТЗ.\n\n"
                "-# Итоговую стоимость назначит дизайнер после ознакомления с ТЗ."
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
            SelectOption(label="Аватарка", value="avatar", emoji="🖼️"),
            SelectOption(label="Баннер", value="banner", emoji="🎨"),
            SelectOption(label="Аватарка + Баннер", value="pack", emoji="📦"),
            SelectOption(label="Оформление VK", value="vk", emoji="🌐"),
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
            embed=Embed(description="⏳ Создаём тикет…").set_footer(text="Heavenly Design © 2026"),
            ephemeral=True,
        )

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
            service=self.service,
            difficulty=DIFFICULTIES[self.difficulty]['name'],
            currency=self.currency,
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
                f"**💰 Стоимость:** будет назначена дизайнером после взятия заказа в работу.\n\n"
                f"-# Как только дизайнер нажмёт «✋ Взяться за заказ» и укажет цену, здесь появятся реквизиты для оплаты."
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
                f"Перейдите в канал {ticket_channel.mention} — там указаны подробности заказа.\n\n"
                f"-# Дизайнер, который возьмётся за заказ, назначит стоимость и реквизиты появятся в тикете."
            )
        )
        done_embed.set_footer(text="Heavenly Design © 2026")
        await inter.edit_original_response(embed=done_embed)


class TakeOrderPriceModal(ui.Modal):
    """Открывается сразу при взятии заказа в работу: дизайнер сначала называет
    стоимость, и только после этого он фиксируется как назначенный дизайнер."""

    def __init__(self, order_data: dict, designer: disnake.Member, take_button: ui.Button, view: "TicketControlView"):
        self.order_data = order_data
        self.designer = designer
        self.take_button = take_button
        self.view = view
        components = [
            ui.TextInput(
                label="・Стоимость заказа:",
                custom_id="price_input",
                style=TextInputStyle.short,
                placeholder="Например: 200",
                max_length=10,
                required=True,
            )
        ]
        super().__init__(title="💰 Заказ принят — укажите цену", custom_id="take_order_price_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        raw_price = inter.text_values["price_input"].strip()
        try:
            price = int(raw_price)
            if price <= 0:
                raise ValueError
        except ValueError:
            await inter.response.send_message("❌ Введите корректное положительное целое число.", ephemeral=True)
            return

        # Фиксируем дизайнера и цену только после успешного заполнения модалки
        await assign_designer_db(inter.channel.id, self.designer.id)
        await set_price_db(inter.channel.id, price)

        self.take_button.disabled = True
        self.take_button.label = f"Дизайнер: {self.designer.display_name}"
        self.take_button.style = ButtonStyle.secondary

        await inter.response.edit_message(view=self.view)

        currency = self.order_data["currency"]
        symbol = CURRENCY_RATES[currency]["symbol"]

        price_embed = Embed(
            description=(
                f"### 🎨 Дизайнер {self.designer.mention} взял заказ в работу!\n"
                f"Назначенная стоимость: **{price} {symbol}**\n\n"
                f"**📦 Реквизиты для оплаты:**\n{REQUISITES[currency]}\n\n"
                f"-# После оплаты нажмите «✅ Оплата получена» (выполняется администрацией)."
            ),
            color=disnake.Color.gold()
        )
        price_embed.set_footer(text="Heavenly Design © 2026")

        customer_mention = f"<@{self.order_data['customer_id']}>"
        await inter.followup.send(content=customer_mention, embed=price_embed)


class ChangePriceModal(ui.Modal):
    """Изменение уже назначенной стоимости (когда заказ ещё не оплачен)."""

    def __init__(self, order_data: dict):
        self.order_data = order_data
        components = [
            ui.TextInput(
                label="・Новая стоимость заказа:",
                custom_id="price_input",
                style=TextInputStyle.short,
                placeholder="Например: 200",
                max_length=10,
                required=True,
            )
        ]
        super().__init__(title="🔄 Изменить стоимость", custom_id="change_price_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        raw_price = inter.text_values["price_input"].strip()
        try:
            price = int(raw_price)
            if price <= 0:
                raise ValueError
        except ValueError:
            await inter.response.send_message("❌ Введите корректное положительное целое число.", ephemeral=True)
            return

        await set_price_db(inter.channel.id, price)

        currency = self.order_data["currency"]
        symbol = CURRENCY_RATES[currency]["symbol"]

        price_embed = Embed(
            description=(
                f"### 🔄 Стоимость заказа изменена\n"
                f"Новая стоимость: **{price} {symbol}**\n\n"
                f"**📦 Реквизиты для оплаты:**\n{REQUISITES[currency]}"
            ),
            color=disnake.Color.gold()
        )
        price_embed.set_footer(text="Heavenly Design © 2026")

        customer_mention = f"<@{self.order_data['customer_id']}>"
        await inter.response.send_message(content=customer_mention, embed=price_embed)


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

        if inter.author.id == order["customer_id"]:
            await inter.response.send_message("❌ Ты че, сам у себя заказ брать собрался?", ephemeral=True)
            return

        if order.get("designer_id"):
            await inter.response.send_message("❌ За этот заказ уже взялся другой дизайнер.", ephemeral=True)
            return

        # Дизайнер сначала называет цену — назначение произойдёт в модалке после ввода
        await inter.response.send_modal(
            modal=TakeOrderPriceModal(order_data=order, designer=inter.author, take_button=button, view=self)
        )

    @ui.button(label="🔄 Изменить стоимость", custom_id="set_price", style=ButtonStyle.secondary)
    async def set_price(self, button: ui.Button, inter: disnake.MessageInteraction):
        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        if not order.get("designer_id"):
            await inter.response.send_message(
                "❌ Сначала нужно взяться за заказ — цена назначается сразу при взятии.", ephemeral=True
            )
            return

        is_designer = order.get("designer_id") == inter.author.id
        if not is_designer and not is_staff(inter.author):
            await inter.response.send_message(
                "❌ Стоимость может изменить только дизайнер, взявший заказ, или администрация.", ephemeral=True
            )
            return

        if order["status"] in ("paid", "work_done"):
            await inter.response.send_message("❌ Заказ уже оплачен, менять стоимость нельзя.", ephemeral=True)
            return

        await inter.response.send_modal(modal=ChangePriceModal(order_data=order))

    @ui.button(label="✅ Оплата получена", custom_id="payment_received", style=ButtonStyle.success)
    async def payment_received(self, button: ui.Button, inter: disnake.MessageInteraction):
        if not inter.author.guild_permissions.administrator:
            await inter.response.send_message("❌ Только администраторы могут подтвердить оплату.", ephemeral=True)
            return

        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        if order["price"] is None:
            await inter.response.send_message(
                "❌ Дизайнер ещё не указал стоимость заказа. Сначала назначьте цену.", ephemeral=True
            )
            return

        if order["status"] in ["paid", "work_done"]:
            await inter.response.send_message("ℹ️ Оплата уже была подтверждена.", ephemeral=True)
            return

        await update_order_status_db(inter.channel.id, "paid")

        button.disabled = True
        button.label = "✅ Оплата подтверждена"

        await inter.response.edit_message(view=self)

        customer_mention = f"<@{order['customer_id']}>"
        confirm_embed = Embed(
            description=(
                "### 💳 Оплата подтверждена!\n"
                f"Подтвердил: {inter.author.mention}\n\n"
                f"-# Дизайнер приступит к работе в ближайшее время."
            )
        )
        confirm_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(content=customer_mention, embed=confirm_embed)

    @ui.button(label="📦 Сдать работу", custom_id="submit_work", style=ButtonStyle.primary)
    async def submit_work(self, button: ui.Button, inter: disnake.MessageInteraction):
        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        is_designer = order.get("designer_id") == inter.author.id
        if not is_designer and not is_staff(inter.author):
            await inter.response.send_message("❌ Только назначенный дизайнер или администрация может сдать работу.", ephemeral=True)
            return

        if order["status"] == "work_done":
            await inter.response.send_message("ℹ️ Работа уже отмечена как выполненная.", ephemeral=True)
            return

        await mark_work_done_db(inter.channel.id)

        button.disabled = True
        button.label = "📦 Работа сдана"

        await inter.response.edit_message(view=self)

        customer_mention = f"<@{order['customer_id']}>"
        work_done_embed = Embed(
            description=(
                f"### 🎨 Работа выполнена!\n"
                f"Уважаемый {customer_mention}, дизайнер сообщил о завершении вашего заказа.\n\n"
                f"**Что нужно сделать:**\n"
                f"1. Проверьте готовый результат.\n"
                f"2. Если всё отлично, нажмите кнопку **«🔒 Завершить заказ»** ниже и оставьте отзыв.\n\n"
                f"⏱️ **Важно:** У вас есть **3 суток** на проверку. Если заказ не будет завершён вручную, через 3 дня он подтвердится **автоматически**."
            ),
            color=disnake.Color.green()
        )
        work_done_embed.set_footer(text="Heavenly Design © 2026")

        await inter.channel.send(
            content=customer_mention,
            embed=work_done_embed,
            view=CompleteOrderView()
        )


class CompleteOrderView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="🔒 Завершить заказ", custom_id="close_ticket", style=ButtonStyle.danger)
    async def close_ticket(self, button: ui.Button, inter: disnake.MessageInteraction):
        order = await get_order_db(inter.channel.id)
        if not order:
            await inter.response.send_message("❌ Заказ не найден в базе данных.", ephemeral=True)
            return

        # ЗАВЕРШИТЬ МОЖЕТ ТОЛЬКО КЛИЕНТ
        if inter.author.id != order["customer_id"]:
            await inter.response.send_message("❌ Завершить заказ и оставить отзыв может **только клиент**.", ephemeral=True)
            return

        await inter.response.send_modal(modal=ReviewModal(order_data=order))


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
        designer_id = self.order_data.get("designer_id")
        designer_mention = f"<@{designer_id}>" if designer_id else "Не назначен"

        service_name = SERVICES.get(self.order_data['service'], {}).get('name', self.order_data['service'])
        price_str = format_price(self.order_data['price'], self.order_data['currency'])

        reviews_channel = inter.guild.get_channel(1529563365708660947)
        if reviews_channel:
            rev_embed = Embed(
                description=(
                    f"### ⭐ Новый отзыв!\n"
                    f"**Заказчик:** {inter.author.mention}\n"
                    f"**Дизайнер:** {designer_mention}\n\n"
                    f"**⚙️ Информация о заказе:**\n"
                    f"・Услуга: **{service_name}**\n"
                    f"・Сложность: **{self.order_data['difficulty']}**\n"
                    f"・Стоимость: **{price_str}**\n\n"
                    f"**Оценка:** {stars_str}\n"
                    f"**💬 Комментарий:**\n{review_text}"
                )
            )
            rev_embed.set_author(name=inter.guild.name, icon_url=inter.guild.icon.url)
            rev_embed.set_footer(text="Heavenly Design © 2026")
            await reviews_channel.send(
                content=designer_mention if designer_id else None,
                embed=rev_embed
            )

        # Начисляем отзыв в базу портфолио дизайнера, если designer_id известен
        if designer_id:
            await _credit_review_to_designer(designer_id, inter.author.id, stars_cnt, review_text)

        await inter.response.send_message(
            embed=Embed(description="🎉 Спасибо за отзыв! Канал будет удалён через 5 секунд.").set_footer(text="Heavenly Design © 2026"),
            ephemeral=True,
        )

        customer_mention = f"<@{self.order_data['customer_id']}>"
        close_embed = Embed(
            description=(
                "### 🎉 Заказ завершён!\n"
                "Спасибо за обращение в **Heavenly Design**!\n\n"
                "-# Канал будет удалён через 5 секунд."
            )
        )
        close_embed.set_footer(text="Heavenly Design © 2026")
        await inter.channel.send(content=customer_mention, embed=close_embed)

        await delete_order_db(inter.channel.id)
        await asyncio.sleep(5)
        try:
            await inter.channel.delete(reason="Заказ завершён")
        except disnake.NotFound:
            pass


class Order(Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.auto_close_check.start()

    def cog_unload(self):
        self.auto_close_check.cancel()

    @tasks.loop(minutes=15)
    async def auto_close_check(self):
        """Проверка заказов, у которых прошло 3 суток со дня сдачи работы"""
        expired_orders = await get_expired_orders_db()
        for row in expired_orders:
            channel_id, customer_id, service, difficulty, currency, price, designer_id = row
            channel = self.bot.get_channel(channel_id)
            if not channel:
                try:
                    channel = await self.bot.fetch_channel(channel_id)
                except Exception:
                    channel = None

            designer_mention = f"<@{designer_id}>" if designer_id else "Не назначен"
            service_name = SERVICES.get(service, {}).get('name', service)
            price_str = format_price(price, currency)

            reviews_channel = self.bot.get_channel(1529563365708660947)
            if reviews_channel:
                rev_embed = Embed(
                    description=(
                        f"### ⭐ Автоматическое завершение заказа!\n"
                        f"**Заказчик:** <@{customer_id}>\n"
                        f"**Дизайнер:** {designer_mention}\n\n"
                        f"**⚙️ Информация о заказе:**\n"
                        f"・Услуга: **{service_name}**\n"
                        f"・Сложность: **{difficulty}**\n"
                        f"・Стоимость: **{price_str}**\n\n"
                        f"**Оценка:** ⭐⭐⭐⭐⭐ (Авто-подтверждение)\n"
                        f"**💬 Комментарий:**\nЗаказ автоматически закрыт по истечению 3 суток после сдачи работы."
                    )
                )
                if channel and channel.guild:
                    rev_embed.set_author(name=channel.guild.name, icon_url=channel.guild.icon.url if channel.guild.icon else None)
                rev_embed.set_footer(text="Heavenly Design © 2026")
                try:
                    await reviews_channel.send(
                        content=designer_mention if designer_id else None,
                        embed=rev_embed
                    )
                except Exception:
                    pass

            if designer_id:
                await _credit_review_to_designer(
                    designer_id, customer_id, 5,
                    "Заказ автоматически закрыт по истечению 3 суток после сдачи работы."
                )

            if channel:
                customer_mention = f"<@{customer_id}>"
                close_embed = Embed(
                    description=(
                        "### ⏱️ Время на проверку истекло!\n"
                        "Заказ был автоматически закрыт и подтверждён, так как прошло 3 суток после сдачи работы.\n\n"
                        "-# Канал будет удалён через 5 секунд."
                    )
                )
                close_embed.set_footer(text="Heavenly Design © 2026")
                try:
                    await channel.send(content=customer_mention, embed=close_embed)
                except Exception:
                    pass

            await delete_order_db(channel_id)
            await asyncio.sleep(5)
            if channel:
                try:
                    await channel.delete(reason="Автоматическое закрытие заказа (3 дня без ответа)")
                except Exception:
                    pass

    @auto_close_check.before_loop
    async def before_auto_close_check(self):
        await self.bot.wait_until_ready()

    @Cog.listener()
    async def on_ready(self):
        self.bot.add_view(StartButton())
        self.bot.add_view(TicketControlView())
        self.bot.add_view(CompleteOrderView())

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
                "**3.** Бот автоматически создаст ваш **личный тикет**\n"
                "**4.** Дизайнер, взявший заказ, сам назначит **стоимость**"
            ),
            color=disnake.Color.from_rgb(114, 137, 218)
        )

        embed.add_field(
            name="💳 Способы оплаты",
            value="**RUB (₽)** | **UAH (₴)** | **Gold <:gold:1529803326898831400>**",
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