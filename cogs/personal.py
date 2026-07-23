import disnake
from disnake.ext import commands
from disnake import ui, Embed, ButtonStyle, TextInputStyle

APPLICATIONS_CHANNEL_ID = 1529873086210506782
DESIGNER_ROLE_ID = 1529564459440275466
HR_ROLE_ID = 1529863867046559854


class ApplicationActionView(ui.View):
    """View с кнопками одобрения/отклонения заявки"""
    def __init__(self, applicant_id: int, role_type: str):
        super().__init__(timeout=None)
        self.add_item(
            ui.Button(
                label="Одобрить",
                style=ButtonStyle.success,
                emoji="✅",
                custom_id=f"app_approve:{applicant_id}:{role_type}"
            )
        )
        self.add_item(
            ui.Button(
                label="Отклонить",
                style=ButtonStyle.danger,
                emoji="❌",
                custom_id=f"app_reject:{applicant_id}:{role_type}"
            )
        )


class DesignerModal(ui.Modal):
    def __init__(self):
        components = [
            ui.TextInput(
                label="・Ваш возраст:",
                custom_id="age_input",
                style=TextInputStyle.short,
                placeholder="Например: 18",
                max_length=3,
                required=True,
            ),
            ui.TextInput(
                label="・Опыт работы:",
                custom_id="exp_input",
                style=TextInputStyle.paragraph,
                placeholder="Опишите ваши навыки и где работали ранее...",
                min_length=10,
                max_length=1000,
                required=True,
            ),
            ui.TextInput(
                label="・Ссылка на портфолио:",
                custom_id="portfolio_input",
                style=TextInputStyle.short,
                placeholder="Behance, Telegram, GitHub или Яндекс.Диск",
                min_length=5,
                max_length=200,
                required=True,
            )
        ]
        super().__init__(title="Анкета: Дизайнер", custom_id="designer_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        age = inter.text_values["age_input"]
        exp = inter.text_values["exp_input"]
        portfolio = inter.text_values["portfolio_input"]

        app_channel = inter.guild.get_channel(APPLICATIONS_CHANNEL_ID)

        embed = Embed(
            description=(
                "### 🎨 Новая заявка: **Дизайнер**\n"
                f"**Пользователь:** {inter.author.mention} (`{inter.author.id}`)\n\n"
                f"**Возраст:** {age}\n"
                f"**Опыт работы:**\n{exp}\n\n"
                f"**Портфолио:**\n{portfolio}"
            ),
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        embed.set_author(name=inter.author.display_name, icon_url=inter.author.display_avatar.url)

        if app_channel:
            await app_channel.send(
                embed=embed,
                view=ApplicationActionView(inter.author.id, "designer")
            )

        await inter.response.send_message(
            embed=Embed(description="✅ Ваша анкета успешно отправлена! Ожидайте ответа администрации.").set_footer(text="Heavenly Design © 2026"),
            ephemeral=True
        )


class HRModal(ui.Modal):
    def __init__(self):
        components = [
            ui.TextInput(
                label="・Ваш возраст:",
                custom_id="age_input",
                style=TextInputStyle.short,
                placeholder="Например: 18",
                max_length=3,
                required=True,
            ),
            ui.TextInput(
                label="・Опыт в найме / PR / привлечении людей:",
                custom_id="exp_input",
                style=TextInputStyle.paragraph,
                placeholder="Расскажите о вашем опыте работы с аудиторией и поиском людей...",
                min_length=10,
                max_length=1000,
                required=True,
            ),
            ui.TextInput(
                label="・Как будете искать дизайнеров и клиентов?",
                custom_id="sourcing_input",
                style=TextInputStyle.paragraph,
                placeholder="Укажите методы завлечения клиентов на сервер и источники поиска дизайнеров...",
                min_length=10,
                max_length=1000,
                required=True,
            ),
            ui.TextInput(
                label="・Ссылка на резюме / примеры работы (если есть):",
                custom_id="portfolio_input",
                style=TextInputStyle.short,
                placeholder="Необязательно (или поставьте прочерк)",
                required=False,
            )
        ]
        super().__init__(title="Анкета: HR / PR-менеджер", custom_id="hr_modal", components=components)

    async def callback(self, inter: disnake.ModalInteraction):
        age = inter.text_values["age_input"]
        exp = inter.text_values["exp_input"]
        sourcing = inter.text_values["sourcing_input"]
        portfolio = inter.text_values["portfolio_input"] or "Не указано"

        app_channel = inter.guild.get_channel(APPLICATIONS_CHANNEL_ID)

        embed = Embed(
            description=(
                "### 🤝 Новая заявка: **HR / PR-менеджер**\n"
                f"**Пользователь:** {inter.author.mention} (`{inter.author.id}`)\n\n"
                f"**Возраст:** {age}\n"
                f"**Опыт работы:**\n{exp}\n\n"
                f"**План по привлечению кадров и клиентов:**\n{sourcing}\n\n"
                f"**Резюме / Дополнительно:**\n{portfolio}"
            ),
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        embed.set_author(name=inter.author.display_name, icon_url=inter.author.display_avatar.url)

        if app_channel:
            await app_channel.send(
                embed=embed,
                view=ApplicationActionView(inter.author.id, "hr")
            )

        await inter.response.send_message(
            embed=Embed(description="✅ Ваша анкета успешно отправлена! Ожидайте ответа администрации.").set_footer(text="Heavenly Design © 2026"),
            ephemeral=True
        )


class ConfirmApplyView(ui.View):
    def __init__(self, role_type: str):
        super().__init__(timeout=120)
        self.role_type = role_type

    @ui.button(label="Согласен, заполнить анкету", style=ButtonStyle.success, emoji="✅")
    async def confirm(self, button: ui.Button, inter: disnake.MessageInteraction):
        if self.role_type == "designer":
            await inter.response.send_modal(modal=DesignerModal())
        else:
            await inter.response.send_modal(modal=HRModal())


class HirePanelView(ui.View):
    def __init__(self):
        super().__init__(timeout=None)

    @ui.button(label="Подать на Дизайнера", custom_id="apply_designer", style=ButtonStyle.primary, emoji="🎨")
    async def apply_designer(self, button: ui.Button, inter: disnake.MessageInteraction):
        embed = Embed(
            description=(
                "### ⚠️ Внимание перед заполнением!\n"
                "Проект берёт **15% комиссию** с каждого выполненного заказа дизайнера на развитие студии.\n\n"
                "Если вы согласны с этими условиями, нажмите кнопку ниже для перехода к анкете."
            ),
            color=disnake.Color.orange()
        )
        await inter.response.send_message(embed=embed, view=ConfirmApplyView("designer"), ephemeral=True)

    @ui.button(label="Подать на HR / PR", custom_id="apply_hr", style=ButtonStyle.secondary, emoji="🤝")
    async def apply_hr(self, button: ui.Button, inter: disnake.MessageInteraction):
        embed = Embed(
            description=(
                "### ⚠️ Внимание перед заполнением!\n"
                "Обратите внимание: проект берёт **15% комиссию** с каждого выполненного заказа дизайнера на развитие студии.\n"
                "Главные задачи HR / PR — активный поиск **новых дизайнеров** и привлечение **обычных участников/клиентов** на сервер.\n\n"
                "Если вы согласны с условиями, нажмите кнопку ниже."
            ),
            color=disnake.Color.orange()
        )
        await inter.response.send_message(embed=embed, view=ConfirmApplyView("hr"), ephemeral=True)


class Recruitment(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @commands.Cog.listener()
    async def on_ready(self):
        self.bot.add_view(HirePanelView())

    @commands.Cog.listener()
    async def on_button_click(self, inter: disnake.MessageInteraction):
        """Слушатель нажатий на кнопки одобрения/отклонения"""
        custom_id = inter.component.custom_id
        if not custom_id.startswith(("app_approve:", "app_reject:")):
            return

        if not (inter.author.guild_permissions.administrator or inter.author.guild_permissions.manage_roles):
            await inter.response.send_message("❌ У вас нет прав для рассмотрения заявок.", ephemeral=True)
            return

        action, applicant_id_str, role_type = custom_id.split(":")
        applicant_id = int(applicant_id_str)

        guild = inter.guild
        member = guild.get_member(applicant_id)
        if not member:
            try:
                member = await guild.fetch_member(applicant_id)
            except disnake.NotFound:
                member = None

        role_id = DESIGNER_ROLE_ID if role_type == "designer" else HR_ROLE_ID
        role_name = "Дизайнер" if role_type == "designer" else "HR / PR-менеджер"

        view = ui.View.from_message(inter.message)
        for child in view.children:
            child.disabled = True

        embed = inter.message.embeds[0]

        if action == "app_approve":
            role_status = ""
            if member:
                role = guild.get_role(role_id)
                if role:
                    try:
                        await member.add_roles(role, reason=f"Заявка одобрена модератором {inter.author}")
                        role_status = f"\n🎭 **Выдана роль:** {role.mention}"
                    except disnake.Forbidden:
                        role_status = "\n⚠️ **Ошибка:** У бота недостаточно прав для выдачи роли."
                    except disnake.HTTPException:
                        role_status = "\n⚠️ **Ошибка:** Не удалось выдать роль."
                else:
                    role_status = "\n⚠️ **Ошибка:** Роль не найдена на сервере."

                try:
                    await member.send(
                        f"🎉 **Поздравляем!** Ваша заявка на должность **{role_name}** на сервере **{guild.name}** была **одобрена**!"
                    )
                except disnake.HTTPException:
                    pass
            else:
                role_status = "\n⚠️ **Пользователь покинул сервер.**"

            embed.color = disnake.Color.green()
            embed.add_field(
                name="Статус решения",
                value=f"✅ **Одобрено** модератором {inter.author.mention}{role_status}",
                inline=False
            )

        elif action == "app_reject":
            if member:
                # Отправка в ЛС
                try:
                    await member.send(
                        f"❌ К сожалению, ваша заявка на должность **{role_name}** на сервере **{guild.name}** была **отклонена**."
                    )
                except disnake.HTTPException:
                    pass

            embed.color = disnake.Color.red()
            embed.add_field(
                name="Статус решения",
                value=f"❌ **Отклонено** модератором {inter.author.mention}",
                inline=False
            )

        await inter.response.edit_message(embed=embed, view=view)

    @commands.command(name="hire_panel")
    @commands.has_permissions(administrator=True)
    async def hire_panel(self, ctx: commands.Context):
        embed = Embed(
            title="✨ НАБОР В КОМАНДУ HEAVENLY DESIGN",
            description=(
                "Мы ищем талантливых специалистов в нашу студию!\n\n"
                "**Открытые вакансии:**\n"
                "🎨 **Дизайнер** — выполнение заказов по графике, оформлению и UI/UX.\n"
                "🤝 **HR / PR-менеджер** — привлечение новых дизайнеров в команду, завлечение клиентов и обычных участников на сервер.\n\n"
                "Нажмите соответствующую кнопку ниже, чтобы ознакомиться с условиями и оставить заявку."
            ),
            color=disnake.Color.from_rgb(114, 137, 218)
        )
        embed.set_footer(text="Heavenly Design © 2026")

        await ctx.message.delete()
        await ctx.send(embed=embed, view=HirePanelView())


def setup(bot: commands.Bot):
    bot.add_cog(Recruitment(bot))