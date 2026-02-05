
from __future__ import annotations
import io
import discord
from discord.ext import commands, tasks
from discord import app_commands
from typing import Dict, Optional, List
from utils.config import load_config, save_config
from utils.perm import is_admin_member

# ============
# Helpers
# ============
def _ticket_overwrites(guild: discord.Guild, opener: discord.Member, admin_role_ids: list[int]) -> Dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
    overwrites: Dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
        guild.default_role: discord.PermissionOverwrite(view_channel=False),
        opener: discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, attach_files=True, embed_links=True)
    }
    # roles admins
    for rid in admin_role_ids:
        role = guild.get_role(rid)
        if role:
            overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True)
    # bot
    me = guild.me
    if me:
        overwrites[me] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, manage_channels=True, manage_messages=True)
    return overwrites

def _can_create_channels(me: discord.Member) -> bool:
    perms = me.guild_permissions
    return perms.manage_channels or perms.administrator

# ============
# UI - Ticket Panel
# ============
class TicketTypeSelect(discord.ui.Select):
    def __init__(self, cog: "TicketsCog"):
        self.cog = cog
        options = [
            discord.SelectOption(label="Denúncia", value="denuncia", emoji="🚨"),
            discord.SelectOption(label="Atualizar Cargos", value="cargos", emoji="🪪"),
            discord.SelectOption(label="Dúvidas", value="duvidas", emoji="❓"),
            discord.SelectOption(label="Exoneração", value="exoneracao", emoji="📤"),
        ]
        super().__init__(
            placeholder="Selecione o tipo de ticket…",
            options=options,
            min_values=1,
            max_values=1,
            custom_id="tickets:type_select"
        )

    async def callback(self, interaction: discord.Interaction):
        val = self.values[0]
        # Fluxos que não abrem ticket
        if val == "exoneracao":
            await interaction.response.send_modal(ExoneracaoModal(self.cog))
            return
        if val == "cargos":
            await interaction.response.send_modal(AtualizarCargosModal(self.cog))
            return

        # Denúncia: se for ADM, a opção vira "Alinhamento" (ticket aberto pelo ADM e seleciona o infrator)
        if val == "denuncia":
            cfg = load_config()
            if is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
                await interaction.response.send_modal(AlinhamentoModal(self.cog))
                return

        await self.cog.open_ticket_channel(interaction, val)

class TicketPanelView(discord.ui.View):
    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=None)
        self.add_item(TicketTypeSelect(cog))

# ============
# UI - Ticket Channel controls
# ============
class TicketControlsView(discord.ui.View):
    def __init__(self, cog: "TicketsCog", opener_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.opener_id = opener_id

    @discord.ui.button(label="Adicionar Policial", style=discord.ButtonStyle.primary, emoji="➕", custom_id="ticket:add_user")
    async def add_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(AddUserModal(self.cog))

    @discord.ui.button(label="Remover Usuário", style=discord.ButtonStyle.secondary, emoji="➖", custom_id="ticket:remove_user")
    async def remove_user(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(RemoveUserModal(self.cog))

    @discord.ui.button(label="Silenciar/Desbloquear", style=discord.ButtonStyle.secondary, emoji="🔇", custom_id="ticket:toggle_mute")
    async def toggle_mute(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)

        # IMPORTANT:
        # Alterar permissões pode demorar e estourar o tempo do interaction.
        # Então a gente dá defer imediatamente e responde via followup.
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            # já respondido/deferido
            pass

        channel = interaction.channel
        if not isinstance(channel, discord.TextChannel):
            return await interaction.followup.send("❌ Canal inválido.", ephemeral=True)

        member = interaction.guild.get_member(self.opener_id)
        if not member:
            try:
                member = await interaction.guild.fetch_member(self.opener_id)
            except Exception:
                member = None
        if not member:
            return await interaction.followup.send("❌ Membro não encontrado.", ephemeral=True)

        ow = channel.overwrites_for(member)
        currently_muted = (ow.send_messages is False)
        ow.view_channel = True
        ow.read_message_history = True
        ow.send_messages = True if currently_muted else False

        try:
            await channel.set_permissions(member, overwrite=ow, reason="Toggle mute no ticket")
        except discord.Forbidden:
            return await interaction.followup.send("❌ Sem permissão para alterar permissões do canal.", ephemeral=True)

        await interaction.followup.send(
            f"✅ {'Desbloqueado' if currently_muted else 'Silenciado'}: {member.mention}",
            ephemeral=True
        )

    @discord.ui.button(label="Finalizar Ticket", style=discord.ButtonStyle.danger, emoji="✅", custom_id="ticket:close")
    async def close(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(CloseTicketModal(self.cog))


class AssumeTicketView(discord.ui.View):
    def __init__(self, cog: "TicketsCog", ticket_channel_id: int, opener_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.ticket_channel_id = ticket_channel_id
        self.opener_id = opener_id

    @discord.ui.button(label="Assumir Ticket", style=discord.ButtonStyle.primary, emoji="🛡️", custom_id="ticket:assume")
    async def assumir(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        await self.cog.assign_ticket(interaction.guild, self.ticket_channel_id, self.opener_id, interaction.user.id)
        await interaction.followup.send("✅ Ticket assumido.", ephemeral=True)

# ============
# Modals
# ============
class AddUserModal(discord.ui.Modal, title="Adicionar Policial ao Ticket"):
    user_id = discord.ui.TextInput(label="ID do usuário", required=True, placeholder="Cole o ID")

    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=180)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.add_user_to_ticket(interaction, int(self.user_id.value.strip()))
        await interaction.followup.send("✅ Usuário adicionado (se existir).", ephemeral=True)

class RemoveUserModal(discord.ui.Modal, title="Remover Usuário do Ticket"):
    user_id = discord.ui.TextInput(label="ID do usuário", required=True)

    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=180)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.remove_user_from_ticket(interaction, int(self.user_id.value.strip()))
        await interaction.followup.send("✅ Usuário removido (se existia).", ephemeral=True)

class CloseTicketModal(discord.ui.Modal, title="Finalizar Ticket"):
    motivo = discord.ui.TextInput(label="Motivo do encerramento", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.close_ticket(interaction, str(self.motivo.value).strip())


class AlinhamentoModal(discord.ui.Modal, title="Denúncia - Iniciar Alinhamento"):
    alvo_id = discord.ui.TextInput(label="ID do infrator (Discord)", required=True, placeholder="Cole o ID")
    resumo = discord.ui.TextInput(
        label="Resumo / Motivo do alinhamento",
        style=discord.TextStyle.paragraph,
        required=True,
        placeholder="Explique o motivo e o que será cobrado no alinhamento"
    )

    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        target_id = int(str(self.alvo_id.value).strip())
        await self.cog.open_alinhamento_ticket(interaction, target_id, str(self.resumo.value).strip())

class AtualizarCargosModal(discord.ui.Modal, title="Solicitação - Atualizar Cargos"):
    nome = discord.ui.TextInput(label="Nome", required=True)
    user_id = discord.ui.TextInput(label="ID", required=True)
    patente = discord.ui.TextInput(label="Patente", required=True)
    unidade = discord.ui.TextInput(label="Unidade", required=True)
    autorizado = discord.ui.TextInput(label="Autorizado por", required=True, placeholder="Quem autorizou?")

    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.handle_cargo_request(interaction, {
            "nome": self.nome.value.strip(),
            "id": self.user_id.value.strip(),
            "patente": self.patente.value.strip(),
            "unidade": self.unidade.value.strip(),
            "autorizado": self.autorizado.value.strip(),
            "solicitante_id": interaction.user.id
        })

class ExoneracaoModal(discord.ui.Modal, title="Solicitação de Exoneração"):
    # Este campo é o "ID no jogo" (ex.: RID). O Discord ID do membro é obtido automaticamente
    # a partir de quem solicitou a exoneração (interaction.user.id).
    user_id = discord.ui.TextInput(label="ID no jogo", required=True)
    nome = discord.ui.TextInput(label="Nome", required=True)
    patente = discord.ui.TextInput(label="Patente", required=True)
    unidade = discord.ui.TextInput(label="Unidade", required=True)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, cog: "TicketsCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.handle_exoneracao_request(interaction, {
            "id": self.user_id.value.strip(),
            "nome": self.nome.value.strip(),
            "patente": self.patente.value.strip(),
            "unidade": self.unidade.value.strip(),
            "motivo": self.motivo.value.strip(),
            "solicitante_id": interaction.user.id
        })

# ============
# Approval Views (cargos / exoneração)
# ============
class CargoDecisionView(discord.ui.View):
    def __init__(self, cog:"TicketsCog", solicitante_id:int):
        super().__init__(timeout=None)
        self.cog = cog
        self.solicitante_id = solicitante_id

    @discord.ui.button(label="Aceitar", style=discord.ButtonStyle.success, emoji="✅")
    async def aceitar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.defer(ephemeral=True)
        await self.cog.notify_user(self.solicitante_id, f"✅ Sua solicitação de **atualização de cargos** foi **ACEITA** por {interaction.user}.")
        await interaction.followup.send("Aceito e notificado.", ephemeral=True)

    @discord.ui.button(label="Recusar", style=discord.ButtonStyle.danger, emoji="⛔")
    async def recusar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(CargoRecusarModal(self.cog, self.solicitante_id))

class CargoRecusarModal(discord.ui.Modal, title="Recusar - Atualização de Cargos"):
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, cog:"TicketsCog", solicitante_id:int):
        super().__init__(timeout=240)
        self.cog=cog
        self.solicitante_id=solicitante_id

    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        await self.cog.notify_user(self.solicitante_id, f"⛔ Sua solicitação de **atualização de cargos** foi **RECUSADA**. Motivo: {self.motivo.value}")
        await interaction.followup.send("Recusado e notificado.", ephemeral=True)

class ExoneracaoDecisionView(discord.ui.View):
    def __init__(self, cog:"TicketsCog", payload:dict):
        super().__init__(timeout=None)
        self.cog=cog
        self.payload=payload

    @discord.ui.button(label="Aprovar", style=discord.ButtonStyle.success, emoji="✅")
    async def aprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg=load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        # Kick pode demorar (fetch_member) e pode falhar por permissão/hierarquia.
        # Então dá defer e responde no followup com status real.
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        ok, detail = await self.cog.approve_exoneracao(interaction, self.payload)
        await interaction.followup.send(
            ("✅ Exoneração aprovada e usuário removido do servidor." if ok else f"⚠️ Exoneração aprovada, mas **não consegui remover** o usuário.\n\n**Detalhe:** {detail}"),
            ephemeral=True
        )

    @discord.ui.button(label="Reprovar", style=discord.ButtonStyle.danger, emoji="⛔")
    async def reprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg=load_config()
        if not is_admin_member(interaction.user, cfg["tickets"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(ExoneracaoRecusarModal(self.cog, self.payload))

class ExoneracaoRecusarModal(discord.ui.Modal, title="Reprovar Exoneração"):
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True)
    def __init__(self, cog:"TicketsCog", payload:dict):
        super().__init__(timeout=240)
        self.cog=cog
        self.payload=payload
    async def on_submit(self, interaction: discord.Interaction):
        await interaction.response.defer(ephemeral=True)
        solicitante_id = int(self.payload.get("solicitante_id",0))
        await self.cog.notify_user(solicitante_id, f"⛔ Sua solicitação de **exoneração** foi **REPROVADA**. Motivo: {self.motivo.value}")
        await interaction.followup.send("Reprovado e notificado.", ephemeral=True)

# ============
# COG
# ============
class TicketsCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.ticket_state: Dict[int, dict] = {}  # channel_id -> {opener_id, admin_id, last_user_ts, last_admin_ts}
        self.reminder_loop.start()

    def cog_unload(self):
        self.reminder_loop.cancel()

    @app_commands.command(name="setup_tickets", description="Cria/atualiza o painel de tickets.")
    async def setup_tickets(self, interaction: discord.Interaction):
        cfg = load_config()
        ch = await interaction.guild.fetch_channel(cfg["tickets"]["panel_channel_id"])
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message("Canal do painel de tickets inválido no config.json.", ephemeral=True)

        embed = discord.Embed(
            title="🎫 Central de Atendimento – Sistema Oficial",
            description="Selecione uma opção abaixo para iniciar o atendimento.",
            color=discord.Color.blurple()
        )
        embed.add_field(name="Opções", value="🚨 Denúncia\n🪪 Atualizar Cargos\n❓ Dúvidas\n📤 Exoneração", inline=False)
        embed.set_footer(text="Hype Police • Atendimento")

        view = TicketPanelView(self)

        panel_msg_id = cfg["tickets"].get("panel_message_id", 0)
        msg=None
        if panel_msg_id:
            try:
                msg = await ch.fetch_message(panel_msg_id)
                await msg.edit(embed=embed, view=view)
            except Exception:
                msg=None
        if msg is None:
            msg = await ch.send(embed=embed, view=view)
            try: await msg.pin()
            except Exception: pass
            cfg["tickets"]["panel_message_id"] = msg.id
            save_config(cfg)

        await interaction.response.send_message("✅ Painel de tickets pronto.", ephemeral=True)

    # ------------
    # Ticket creation
    # ------------
    async def open_ticket_channel(self, interaction: discord.Interaction, kind: str):
        cfg = load_config()
        guild = interaction.guild
        opener: discord.Member = interaction.user  # type: ignore

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        me = guild.me
        if not me or not _can_create_channels(me):
            return await interaction.followup.send("❌ Bot sem permissão **Gerenciar Canais**.", ephemeral=True)

        # fetch category
        category = guild.get_channel(cfg["tickets"]["category_id"])
        if category is None:
            try:
                category = await guild.fetch_channel(cfg["tickets"]["category_id"])
            except Exception:
                category = None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send("❌ Categoria de tickets inválida no config.json.", ephemeral=True)

        overwrites = _ticket_overwrites(guild, opener, cfg["tickets"]["admin_role_ids"])

        # create channel
        name = f"{kind}-{opener.display_name}".lower().replace(" ", "-")[:90]
        try:
            ticket_channel = await guild.create_text_channel(
                name=name,
                category=category,
                overwrites=overwrites,
                reason="Abrir ticket"
            )
        except discord.Forbidden:
            return await interaction.followup.send(
                "❌ **403 Missing Permissions** ao criar o canal.\n"
                "Verifique permissões do bot **na categoria de tickets** (View Channel + Manage Channels) "
                "e se a categoria não está bloqueando o bot.",
                ephemeral=True
            )

        # notify channel
        embed = discord.Embed(
            title="📌 Ticket Aberto",
            description=f"Tipo: **{kind.upper()}**\nSolicitante: {opener.mention}",
            color=discord.Color.green()
        )
        
        # Mensagem inicial dentro do ticket (fixada) conforme o tipo
        initial_map = {
            "duvidas": (
                "❓ Dúvidas",
                "Utilize este espaço para esclarecer dúvidas relacionadas a procedimentos, regras, cursos ou funcionamento interno da Polícia."
            ),
            "denuncia": (
                "🚨 Denúncia",
                "Espaço para denunciar policiais que descumpram regras, procedimentos ou ajam de forma inadequada dentro da corporação."
            ),
        }
        title, desc = initial_map.get(kind, ("🎫 Ticket", ""))
        intro = discord.Embed(title=title, description=desc, color=discord.Color.dark_grey())
        intro.set_footer(text="Aguarde um ADM assumir o atendimento.")
        try:
            intro_msg = await ticket_channel.send(embed=intro)
            await intro_msg.pin(reason="Mensagem inicial do ticket")
        except Exception:
            pass

        await ticket_channel.send(embed=embed, view=TicketControlsView(self, opener.id))

        # notify admin channel
        adm_ch = await guild.fetch_channel(cfg["tickets"]["channel_adm_ticket_id"])
        adm_embed = discord.Embed(
            title="🛡️ Novo Ticket",
            description=f"Tipo: **{kind.upper()}**\nSolicitante: {opener.mention}\nCanal: {ticket_channel.mention}",
            color=discord.Color.orange()
        )
        await adm_ch.send(embed=adm_embed, view=AssumeTicketView(self, ticket_channel.id, opener.id))

        # init state
        self.ticket_state[ticket_channel.id] = {
            "opener_id": opener.id,
            "admin_id": 0,
            "last_user_ts": discord.utils.utcnow().timestamp(),
            "last_admin_ts": discord.utils.utcnow().timestamp(),
        }

        await interaction.followup.send(f"✅ Ticket criado: {ticket_channel.mention}", ephemeral=True)


    async def open_alinhamento_ticket(self, interaction: discord.Interaction, target_id: int, resumo: str):
        """Fluxo de denúncia usado por ADM: abre um ticket e coloca o infrator dentro do canal."""
        cfg = load_config()
        guild = interaction.guild
        opener_admin: discord.Member = interaction.user  # type: ignore

        # Confere permissão ADM novamente
        if not is_admin_member(opener_admin, cfg["tickets"]["admin_role_ids"]):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        me = guild.me
        if not me or not _can_create_channels(me):
            return await interaction.followup.send("❌ Bot sem permissão **Gerenciar Canais**.", ephemeral=True)

        # categoria
        category = guild.get_channel(cfg["tickets"]["category_id"])
        if category is None:
            try:
                category = await guild.fetch_channel(cfg["tickets"]["category_id"])
            except Exception:
                category = None
        if not isinstance(category, discord.CategoryChannel):
            return await interaction.followup.send("❌ Categoria de tickets inválida no config.json.", ephemeral=True)

        # alvo
        target_member = guild.get_member(target_id)
        if not target_member:
            try:
                target_member = await guild.fetch_member(target_id)
            except Exception:
                target_member = None

        # permissões: cria com opener como um "placeholder" e depois garante o alvo
        overwrites = _ticket_overwrites(guild, opener_admin, cfg["tickets"]["admin_role_ids"])
        if target_member:
            overwrites[target_member] = discord.PermissionOverwrite(
                view_channel=True,
                send_messages=True,
                read_message_history=True,
                attach_files=True,
                embed_links=True
            )

        # canal
        name_base = (target_member.display_name if target_member else str(target_id))
        name = f"alinhamento-{name_base}".lower().replace(" ", "-")[:90]
        try:
            ticket_channel = await guild.create_text_channel(
                name=name,
                category=category,
                overwrites=overwrites,
                reason="Abrir ticket de alinhamento"
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ Sem permissão para criar canal na categoria de tickets.", ephemeral=True)

        # Mensagem inicial
        embed = discord.Embed(
            title="🧭 Alinhamento (Denúncia)",
            description=(
                f"**Iniciado por:** {opener_admin.mention}\n"
                f"**Alvo:** {target_member.mention if target_member else f'ID `{target_id}` (não encontrado)'}\n\n"
                f"**Resumo:**\n{resumo[:1200]}"
            ),
            color=discord.Color.orange()
        )
        embed.set_footer(text="Use este canal para orientar, cobrar e registrar o alinhamento.")
        try:
            intro_msg = await ticket_channel.send(embed=embed)
            await intro_msg.pin(reason="Mensagem inicial do alinhamento")
        except Exception:
            pass

        # Controles do ticket (opener_id é o alvo)
        await ticket_channel.send(
            embed=discord.Embed(title="📌 Ticket Aberto", description="Controles do ticket abaixo.", color=discord.Color.green()),
            view=TicketControlsView(self, target_id)
        )

        # Aviso no canal ADM (sem precisar assumir)
        adm_ch = await guild.fetch_channel(cfg["tickets"]["channel_adm_ticket_id"])
        adm_embed = discord.Embed(
            title="🛡️ Novo Alinhamento (Denúncia)",
            description=f"Canal: {ticket_channel.mention}\nAlvo: {target_member.mention if target_member else f'`{target_id}`'}\nIniciado por: {opener_admin.mention}",
            color=discord.Color.orange()
        )
        await adm_ch.send(embed=adm_embed)

        # Estado: considera o alvo como "opener" e o ADM já assumido
        now = discord.utils.utcnow().timestamp()
        self.ticket_state[ticket_channel.id] = {
            "opener_id": target_id,
            "admin_id": opener_admin.id,
            "last_user_ts": now,
            "last_admin_ts": now,
        }

        await interaction.followup.send(f"✅ Alinhamento criado: {ticket_channel.mention}", ephemeral=True)

    async def assign_ticket(self, guild: discord.Guild, channel_id: int, opener_id: int, admin_id: int):
        # set state
        st = self.ticket_state.get(channel_id, {"opener_id": opener_id, "admin_id": 0, "last_user_ts": discord.utils.utcnow().timestamp(), "last_admin_ts": discord.utils.utcnow().timestamp()})
        st["admin_id"] = admin_id
        self.ticket_state[channel_id] = st

        try:
            ch = await guild.fetch_channel(channel_id)
        except Exception:
            return
        if isinstance(ch, discord.TextChannel):
            await ch.send(f"🛡️ Ticket assumido por <@{admin_id}>.")

    # ------------
    # Ticket controls
    # ------------
    async def add_user_to_ticket(self, interaction: discord.Interaction, user_id: int):
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return
        try:
            member = await interaction.guild.fetch_member(user_id)
        except Exception:
            return
        await ch.set_permissions(member, view_channel=True, send_messages=True, read_message_history=True)

    async def remove_user_from_ticket(self, interaction: discord.Interaction, user_id: int):
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return
        try:
            member = await interaction.guild.fetch_member(user_id)
        except Exception:
            return
        await ch.set_permissions(member, overwrite=None)

    async def close_ticket(self, interaction: discord.Interaction, motivo: str):
        cfg = load_config()
        ch = interaction.channel
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("❌ Canal inválido.", ephemeral=True)

        st = self.ticket_state.get(ch.id, {})
        opener_id = int(st.get("opener_id", 0))
        admin_id = int(st.get("admin_id", 0))

        # transcript
        buf = io.StringIO()
        async for msg in ch.history(limit=2000, oldest_first=True):
            buf.write(f"[{msg.created_at.isoformat()}] {msg.author} ({msg.author.id}): {msg.content}\n")
        txt = buf.getvalue().encode("utf-8")
        file = discord.File(io.BytesIO(txt), filename=f"transcript-{ch.id}.txt")

        reg = await interaction.guild.fetch_channel(cfg["tickets"]["channel_registro_ticket_id"])
        await reg.send(content=f"🧾 Ticket {ch.name} finalizado. Motivo: {motivo}", file=file)

        # DM notify
        if opener_id:
            await self.notify_user(opener_id, f"✅ Seu ticket **{ch.name}** foi finalizado. Motivo: {motivo}")
        if admin_id:
            await self.notify_user(admin_id, f"✅ Você finalizou o ticket **{ch.name}**. Motivo: {motivo}")

        # delete channel
        try:
            await ch.delete(reason=f"Ticket finalizado: {motivo}")
        except Exception:
            pass

        self.ticket_state.pop(ch.id, None)

    # ------------
    # Reminders (1h)
    # ------------
    @tasks.loop(minutes=5)
    async def reminder_loop(self):
        cfg = load_config()
        guild = self.bot.get_guild(cfg["guild_id"])
        if not guild:
            return
        now = discord.utils.utcnow().timestamp()
        limit_sec = int(cfg["tickets"].get("notify_after_minutes", 60)) * 60

        for ch_id, st in list(self.ticket_state.items()):
            admin_id = int(st.get("admin_id", 0))
            opener_id = int(st.get("opener_id", 0))
            # if no admin assigned yet, skip reminders
            if not admin_id or not opener_id:
                continue

            # We can't reliably detect last message author without message listeners here.
            # Minimal: ping both if ticket exists and idle > limit
            last = float(min(st.get("last_user_ts", now), st.get("last_admin_ts", now)))
            if now - last > limit_sec:
                await self.notify_user(admin_id, "⏰ Você tem um ticket sem resposta há mais de 1 hora.")
                await self.notify_user(opener_id, "⏰ Seu ticket está sem resposta há mais de 1 hora. Aguarde ou reabra se necessário.")
                st["last_user_ts"] = now
                st["last_admin_ts"] = now
                self.ticket_state[ch_id] = st

    @commands.Cog.listener("on_message")
    async def on_message(self, msg: discord.Message):
        if not msg.guild or msg.author.bot:
            return
        st = self.ticket_state.get(msg.channel.id)
        if not st:
            return
        now = discord.utils.utcnow().timestamp()
        # update last message timestamps
        if int(st.get("admin_id", 0)) == msg.author.id:
            st["last_admin_ts"] = now
        elif int(st.get("opener_id", 0)) == msg.author.id:
            st["last_user_ts"] = now
        self.ticket_state[msg.channel.id] = st

    # ------------
    # Cargo request
    # ------------
    async def handle_cargo_request(self, interaction: discord.Interaction, data: dict):
        cfg = load_config()
        reg = await interaction.guild.fetch_channel(cfg["tickets"]["channel_registro_ticket_id"])
        solicitante_id = int(data["solicitante_id"])

        embed = discord.Embed(title="🪪 Solicitação - Atualizar Cargos", color=discord.Color.blue())
        embed.add_field(name="Solicitante", value=f"<@{solicitante_id}>", inline=False)
        embed.add_field(name="Nome", value=data["nome"], inline=True)
        embed.add_field(name="ID", value=data["id"], inline=True)
        embed.add_field(name="Patente", value=data["patente"], inline=True)
        embed.add_field(name="Unidade", value=data["unidade"], inline=True)
        embed.add_field(name="Autorizado", value=data["autorizado"], inline=False)

        await reg.send(embed=embed, view=CargoDecisionView(self, solicitante_id))
        await interaction.followup.send("✅ Solicitação enviada para análise.", ephemeral=True)

    # ------------
    # Exoneração flow (no ticket)
    # ------------
    async def handle_exoneracao_request(self, interaction: discord.Interaction, data: dict):
        cfg = load_config()
        adm = await interaction.guild.fetch_channel(cfg["tickets"]["channel_adm_ticket_id"])

        embed = discord.Embed(title="📤 Solicitação de Exoneração", color=discord.Color.red())
        embed.add_field(name="Solicitante", value=f"<@{int(data['solicitante_id'])}>", inline=False)
        embed.add_field(name="ID no jogo", value=data["id"], inline=True)
        embed.add_field(name="Nome", value=data["nome"], inline=True)
        embed.add_field(name="Patente", value=data["patente"], inline=True)
        embed.add_field(name="Unidade", value=data["unidade"], inline=True)
        embed.add_field(name="Motivo", value=data["motivo"][:1000], inline=False)

        await adm.send(embed=embed, view=ExoneracaoDecisionView(self, data))
        await interaction.followup.send("✅ Solicitação enviada para análise (ADM).", ephemeral=True)

    async def approve_exoneracao(self, interaction: discord.Interaction, payload: dict) -> tuple[bool, str]:
        cfg = load_config()
        guild = interaction.guild
        ex_ch = await guild.fetch_channel(cfg["exoneracao"]["channel_exonerados_id"])

        # IMPORTANTe: o alvo a ser removido do servidor é SEMPRE quem solicitou a exoneração.
        # O campo "id" do payload é o ID no jogo (RID) e NÃO deve ser usado para kick.
        solicitante_id = int(payload.get("solicitante_id", 0))
        target_discord_id = solicitante_id
        game_id = str(payload.get("id", "-")).strip()
        nome = payload.get("nome", "(sem nome)")
        patente = payload.get("patente", "-")
        unidade = payload.get("unidade", "-")
        motivo = payload.get("motivo", "-")
        approver = interaction.user

        embed = discord.Embed(title="✅ Exoneração aprovada", color=discord.Color.dark_red())
        embed.add_field(name="Usuário", value=f"{nome} (Discord: <@{target_discord_id}> | ID no jogo: {game_id})", inline=False)
        embed.add_field(name="Patente / Unidade", value=f"{patente} • {unidade}", inline=False)
        embed.add_field(name="Motivo", value=str(motivo)[:1000], inline=False)
        embed.add_field(name="Aprovado por", value=f"{approver.mention}", inline=False)

        await ex_ch.send(embed=embed)

        # --- remover do servidor (kick) ---
        me = guild.me
        if not me or not (me.guild_permissions.kick_members or me.guild_permissions.administrator):
            # notifica e retorna falha clara
            await ex_ch.send("⚠️ **Falha ao remover:** o bot não tem permissão de **Expulsar Membros (Kick Members)**.")
            removed = False
            detail = "Bot sem permissão Kick Members"
        else:
            removed = False
            detail = ""
            try:
                if target_discord_id == 0:
                    removed = False
                    detail = "Solicitante inválido (ID 0)"
                    await ex_ch.send("⚠️ **Falha ao remover:** não consegui identificar o solicitante (ID 0).")
                    # nada mais a fazer
                    raise RuntimeError("invalid_target_id")

                member = guild.get_member(target_discord_id)
                if not member:
                    member = await guild.fetch_member(target_discord_id)

                # hierarquia de cargos (bot precisa estar acima)
                if me.top_role <= member.top_role and not me.guild_permissions.administrator:
                    removed = False
                    detail = "Hierarquia: cargo do bot abaixo/igual ao cargo do membro"
                    await ex_ch.send("⚠️ **Falha ao remover:** hierarquia de cargos impede o kick (cargo do bot precisa estar acima do membro).")
                else:
                    await member.kick(reason=f"Exoneração aprovada por {approver} | Motivo: {str(motivo)[:200]}")
                    removed = True
                    detail = ""
            except discord.NotFound:
                removed = False
                detail = "Membro não encontrado no servidor"
                await ex_ch.send("⚠️ **Falha ao remover:** esse ID não está no servidor.")
            except discord.Forbidden:
                removed = False
                detail = "Forbidden (permissão/hierarquia)"
                await ex_ch.send("⚠️ **Falha ao remover:** o Discord bloqueou (permissão/hierarquia).")
            except RuntimeError as e:
                if str(e) != "invalid_target_id":
                    removed = False
                    detail = f"Erro: {type(e).__name__}"
                    await ex_ch.send(f"⚠️ **Falha ao remover:** erro inesperado ({type(e).__name__}).")
            except Exception as e:
                removed = False
                detail = f"Erro: {type(e).__name__}"
                await ex_ch.send(f"⚠️ **Falha ao remover:** erro inesperado ({type(e).__name__}).")

        # notify requester
        if solicitante_id:
            await self.notify_user(
                solicitante_id,
                (f"✅ Exoneração aprovada por {approver}.\nUsuário: {nome} (ID no jogo: {game_id}).\nRemoção do servidor: {'✅ OK' if removed else '⚠️ NÃO FOI POSSÍVEL'}." + (f"\nDetalhe: {detail}" if detail else ""))
            )

        return removed, (detail or "OK")

    # ------------
    # DM utility
    # ------------
    async def notify_user(self, user_id: int, content: str):
        if user_id == 0:
            return
        try:
            user = await self.bot.fetch_user(user_id)
            await user.send(content)
        except Exception:
            pass

async def setup(bot: commands.Bot):
    cog = TicketsCog(bot)
    bot.add_view(TicketPanelView(cog))
    await bot.add_cog(cog)