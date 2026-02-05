from __future__ import annotations

import discord
from discord.ext import commands
from discord import app_commands

from utils.config import load_config, save_config
from utils.perm import is_admin_member


def _get_admin_role_ids(cfg: dict) -> list[int]:
    ap = cfg.get("admin_panel", {})
    ids = ap.get("admin_role_ids")
    if isinstance(ids, list) and ids:
        return [int(x) for x in ids]
    # fallback
    return [int(x) for x in cfg.get("tickets", {}).get("admin_role_ids", [])]


def _get_adv_role_map(cfg: dict) -> dict[str, int]:
    p = cfg.get("punicao", {})
    rm = p.get("adv_role_ids", {})
    out: dict[str, int] = {}
    if isinstance(rm, dict):
        for k, v in rm.items():
            try:
                out[str(k)] = int(v)
            except Exception:
                continue
    return out


def _get_punicao_channel_id(cfg: dict) -> int:
    try:
        return int(cfg.get("punicao", {}).get("channel_punicao_id", 0))
    except Exception:
        return 0


class ExonerarAdminModal(discord.ui.Modal, title="Exonerar (Admin)"):
    discord_id = discord.ui.TextInput(label="ID do Discord", required=True, placeholder="Cole o ID do Discord")
    nome = discord.ui.TextInput(label="Nome", required=True)
    patente = discord.ui.TextInput(label="Patente", required=True)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True, max_length=900)

    def __init__(self, cog: "AdminPanelCog", kind: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.kind = kind  # "EXONERAR" ou "DESLIGAMENTO"

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        cfg = load_config()
        admin_ids = _get_admin_role_ids(cfg)
        if not is_admin_member(interaction.user, admin_ids):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        # parse target id
        try:
            target_id = int(str(self.discord_id.value).strip())
        except Exception:
            return await interaction.followup.send("❌ ID do Discord inválido.", ephemeral=True)

        removed, detail = await self.cog.kick_member(
            guild=interaction.guild,
            target_id=target_id,
            reason=f"{self.kind}: {self.motivo.value}"[:450],
        )

        # log to exonerados
        ex_ch_id = int(cfg.get("exoneracao", {}).get("channel_exonerados_id", 0))
        if ex_ch_id:
            try:
                ex_ch = await interaction.guild.fetch_channel(ex_ch_id)
            except Exception:
                ex_ch = None
            if isinstance(ex_ch, discord.TextChannel):
                embed = discord.Embed(
                    title=f"📤 {self.kind} aprovado",
                    description=(
                        f"**Nome:** {self.nome.value}\n"
                        f"**Patente:** {self.patente.value}\n"
                        f"**Discord:** <@{target_id}> (`{target_id}`)\n"
                        f"**Motivo:** {self.motivo.value}\n\n"
                        f"**Aprovado por:** {interaction.user.mention}\n"
                        f"**Remoção do servidor:** {'✅ OK' if removed else '⚠️ NÃO FOI POSSÍVEL'}"
                    ),
                    color=discord.Color.red() if removed else discord.Color.orange(),
                )
                if not removed and detail:
                    embed.set_footer(text=f"Detalhe: {detail}")
                await ex_ch.send(embed=embed)

        await interaction.followup.send(
            f"✅ {self.kind} registrado. Remoção do servidor: {'✅ OK' if removed else '⚠️ NÃO FOI POSSÍVEL'}" + (f"\nDetalhe: {detail}" if detail and not removed else ""),
            ephemeral=True,
        )


class AlinharAdminModal(discord.ui.Modal, title="Alinhar Membro"):
    nome = discord.ui.TextInput(label="Nome", required=True)
    discord_id = discord.ui.TextInput(label="ID do Discord", required=True)
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True, max_length=900)

    def __init__(self, cog: "AdminPanelCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        cfg = load_config()
        admin_ids = _get_admin_role_ids(cfg)
        if not is_admin_member(interaction.user, admin_ids):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        try:
            target_id = int(str(self.discord_id.value).strip())
        except Exception:
            return await interaction.followup.send("❌ ID do Discord inválido.", ephemeral=True)

        # DM alvo (24h)
        await self.cog.notify_user(
            target_id,
            "⚠️ Você está sendo **ALINHADO(A)** pelo RH da policia militar do hype.\n"
            f"**Motivo:** {self.motivo.value}\n\n"
            "Você tem **24 horas** para responder neste ticket e se posicionar."
        )

        # abrir ticket de alinhamento reutilizando o TicketsCog
        tickets_cog = self.cog.bot.get_cog("TicketsCog")
        if not tickets_cog:
            return await interaction.followup.send("❌ TicketsCog não carregado. Verifique se a extensão cogs.tickets está ativa.", ephemeral=True)

        resumo = f"Nome informado: **{self.nome.value}**\nMotivo: {self.motivo.value}"
        await tickets_cog.open_alinhamento_ticket(interaction, target_id, resumo)


class AnuncioAdminModal(discord.ui.Modal, title="Anúncio"):
    titulo = discord.ui.TextInput(label="Título", required=True, max_length=120)
    texto = discord.ui.TextInput(label="Texto", style=discord.TextStyle.paragraph, required=True, max_length=1800)
    canal_id = discord.ui.TextInput(label="ID do canal", required=True, placeholder="Cole o ID do canal onde enviar")

    def __init__(self, cog: "AdminPanelCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        cfg = load_config()
        admin_ids = _get_admin_role_ids(cfg)
        if not is_admin_member(interaction.user, admin_ids):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        try:
            ch_id = int(str(self.canal_id.value).strip())
        except Exception:
            return await interaction.followup.send("❌ ID do canal inválido.", ephemeral=True)

        try:
            ch = await interaction.guild.fetch_channel(ch_id)
        except Exception:
            ch = None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("❌ Canal não encontrado ou não é um canal de texto.", ephemeral=True)

        embed = discord.Embed(title=str(self.titulo.value).strip(), description=str(self.texto.value).strip(), color=discord.Color.blurple())
        embed.set_footer(text=f"Anúncio enviado por {interaction.user}")

        try:
            await ch.send(
                content="@everyone",
                embed=embed,
                allowed_mentions=discord.AllowedMentions(everyone=True)
            )
        except discord.Forbidden:
            return await interaction.followup.send("❌ Sem permissão para enviar mensagem nesse canal.", ephemeral=True)

        await interaction.followup.send(f"✅ Anúncio enviado em {ch.mention}.", ephemeral=True)


ADV_LABELS = {
    "adv1": "ADV 1",
    "adv2": "ADV 2",
    "adv3": "ADV 3",
    "adv_formal": "ADV Formal",
}


class AdvModal(discord.ui.Modal, title="Aplicar Advertência (ADV)"):
    discord_id = discord.ui.TextInput(label="ID do Discord (alvo)", required=True, placeholder="Cole o ID do Discord")
    id_policial = discord.ui.TextInput(label="ID do Policial", required=True, placeholder="Ex: RID / ID do jogo")
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True, max_length=900)
    punicao = discord.ui.TextInput(label="Punição", required=True, placeholder="Ex: 2 dias / suspensão / etc", max_length=120)

    def __init__(self, cog: "AdminPanelCog", adv_key: str):
        super().__init__(timeout=300)
        self.cog = cog
        self.adv_key = adv_key

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        cfg = load_config()
        admin_ids = _get_admin_role_ids(cfg)
        if not is_admin_member(interaction.user, admin_ids):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        try:
            target_id = int(str(self.discord_id.value).strip())
        except Exception:
            return await interaction.followup.send("❌ ID do Discord inválido.", ephemeral=True)

        role_map = _get_adv_role_map(cfg)
        role_id = int(role_map.get(self.adv_key, 0) or 0)
        if role_id == 0:
            return await interaction.followup.send("❌ Configure os IDs dos cargos ADV em `punicao.adv_role_ids` no config.json.", ephemeral=True)

        # buscar membro e cargo
        guild = interaction.guild
        member = guild.get_member(target_id)
        if not member:
            try:
                member = await guild.fetch_member(target_id)
            except discord.NotFound:
                member = None

        if not member:
            return await interaction.followup.send("❌ Esse ID não está no servidor.", ephemeral=True)

        role = guild.get_role(role_id)
        if not role:
            return await interaction.followup.send("❌ Cargo ADV não encontrado no servidor (verifique o ID no config).", ephemeral=True)

        # aplicar cargo
        ok_role = True
        detail = ""
        try:
            await member.add_roles(role, reason=f"ADV aplicado por {interaction.user} | {self.motivo.value}"[:450])
        except discord.Forbidden:
            ok_role = False
            detail = "Forbidden (permissão/hierarquia)"
        except Exception as e:
            ok_role = False
            detail = f"Erro: {type(e).__name__}"

        # montar embed
        adv_name = ADV_LABELS.get(self.adv_key, self.adv_key)
        embed = discord.Embed(
            title=f"⚠️ {adv_name} aplicada",
            description=(
                f"**Alvo:** {member.mention} (`{member.id}`)\n"
                f"**ID do policial:** {self.id_policial.value}\n"
                f"**Motivo:** {self.motivo.value}\n"
                f"**Punição:** {self.punicao.value}\n\n"
                f"**Aplicado por:** {interaction.user.mention}"
            ),
            color=discord.Color.orange() if ok_role else discord.Color.red(),
        )
        if not ok_role and detail:
            embed.set_footer(text=f"Cargo não aplicado: {detail}")

        # enviar no canal de punição
        ch_id = _get_punicao_channel_id(cfg)
        if ch_id:
            try:
                ch = await guild.fetch_channel(int(ch_id))
            except Exception:
                ch = None
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

        # DM para o punido
        await self.cog.notify_user(
            member.id,
            "⚠️ Você recebeu uma **ADVERTÊNCIA (ADV)**.\n"
            f"**Tipo:** {adv_name}\n"
            f"**Motivo:** {self.motivo.value}\n"
            f"**Punição:** {self.punicao.value}\n"
            f"**Aplicado por:** {interaction.user}"
        )

        await interaction.followup.send(
            f"✅ ADV registrada e enviada. Cargo: {'✅ aplicado' if ok_role else '⚠️ não foi possível aplicar'}.",
            ephemeral=True,
        )


class AdvSelect(discord.ui.Select):
    def __init__(self, cog: "AdminPanelCog"):
        self.cog = cog
        options = [
            discord.SelectOption(label=ADV_LABELS[k], value=k) for k in ("adv1", "adv2", "adv3", "adv_formal")
        ]
        super().__init__(placeholder="Selecione o tipo de ADV...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        adv_key = str(self.values[0])
        await interaction.response.send_modal(AdvModal(self.cog, adv_key=adv_key))


class AdvSelectView(discord.ui.View):
    def __init__(self, cog: "AdminPanelCog"):
        super().__init__(timeout=180)
        self.add_item(AdvSelect(cog))


class RevogarPuniModal(discord.ui.Modal, title="Revogar Punição (ADV)"):
    discord_id = discord.ui.TextInput(label="ID do Discord (alvo)", required=True, placeholder="Cole o ID do Discord")
    motivo = discord.ui.TextInput(label="Motivo da revogação", style=discord.TextStyle.paragraph, required=True, max_length=900)

    def __init__(self, cog: "AdminPanelCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        try:
            target_id = int(str(self.discord_id.value).strip())
        except Exception:
            return await interaction.followup.send("❌ ID do Discord inválido.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(target_id)
        if not member:
            try:
                member = await guild.fetch_member(target_id)
            except discord.NotFound:
                member = None
        if not member:
            return await interaction.followup.send("❌ Esse ID não está no servidor.", ephemeral=True)

        # descobrir quais ADVs a pessoa tem
        role_map = _get_adv_role_map(cfg)
        present: list[tuple[str, discord.Role]] = []
        for k, rid in role_map.items():
            try:
                rid_int = int(rid)
            except Exception:
                continue
            if rid_int == 0:
                continue
            r = guild.get_role(rid_int)
            if r and r in member.roles:
                present.append((k, r))

        if not present:
            return await interaction.followup.send("ℹ️ Essa pessoa não possui cargos de ADV configurados.", ephemeral=True)

        await interaction.followup.send(
            "Selecione qual ADV remover:",
            view=RevogarSelectView(self.cog, target_id=member.id, motivo=str(self.motivo.value), roles_present=present),
            ephemeral=True,
        )


class RevogarSelect(discord.ui.Select):
    def __init__(self, cog: "AdminPanelCog", target_id: int, motivo: str, roles_present: list[tuple[str, discord.Role]]):
        self.cog = cog
        self.target_id = target_id
        self.motivo = motivo
        options = []
        for k, role in roles_present:
            options.append(discord.SelectOption(label=ADV_LABELS.get(k, role.name), value=k, description=role.name))
        super().__init__(placeholder="Escolha a ADV para remover...", min_values=1, max_values=1, options=options)

    async def callback(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.followup.send("Apenas ADM.", ephemeral=True)

        adv_key = str(self.values[0])
        role_map = _get_adv_role_map(cfg)
        role_id = int(role_map.get(adv_key, 0) or 0)
        if role_id == 0:
            return await interaction.followup.send("❌ Cargo ADV não configurado no config.json.", ephemeral=True)

        guild = interaction.guild
        member = guild.get_member(self.target_id)
        if not member:
            try:
                member = await guild.fetch_member(self.target_id)
            except discord.NotFound:
                member = None
        if not member:
            return await interaction.followup.send("❌ Esse ID não está no servidor.", ephemeral=True)

        role = guild.get_role(role_id)
        if not role:
            return await interaction.followup.send("❌ Cargo ADV não encontrado no servidor (verifique o ID).", ephemeral=True)

        ok = True
        detail = ""
        try:
            await member.remove_roles(role, reason=f"Revogação ADV por {interaction.user} | {self.motivo}"[:450])
        except discord.Forbidden:
            ok = False
            detail = "Forbidden (permissão/hierarquia)"
        except Exception as e:
            ok = False
            detail = f"Erro: {type(e).__name__}"

        adv_name = ADV_LABELS.get(adv_key, role.name)
        embed = discord.Embed(
            title=f"♻️ {adv_name} removida",
            description=(
                f"**Alvo:** {member.mention} (`{member.id}`)\n"
                f"**ADV removida:** {adv_name}\n"
                f"**Motivo:** {self.motivo}\n\n"
                f"**Removido por:** {interaction.user.mention}"
            ),
            color=discord.Color.green() if ok else discord.Color.red(),
        )
        if not ok and detail:
            embed.set_footer(text=f"Cargo não removido: {detail}")

        ch_id = _get_punicao_channel_id(cfg)
        if ch_id:
            try:
                ch = await guild.fetch_channel(int(ch_id))
            except Exception:
                ch = None
            if isinstance(ch, discord.TextChannel):
                try:
                    await ch.send(embed=embed)
                except Exception:
                    pass

        await self.cog.notify_user(
            member.id,
            "✅ Uma **ADVERTÊNCIA (ADV)** foi removida.\n"
            f"**ADV removida:** {adv_name}\n"
            f"**Motivo:** {self.motivo}\n"
            f"**Removido por:** {interaction.user}"
        )

        await interaction.followup.send(f"✅ Processado. Cargo removido: {'✅' if ok else '⚠️ não foi possível'}.", ephemeral=True)


class RevogarSelectView(discord.ui.View):
    def __init__(self, cog: "AdminPanelCog", target_id: int, motivo: str, roles_present: list[tuple[str, discord.Role]]):
        super().__init__(timeout=180)
        self.add_item(RevogarSelect(cog, target_id=target_id, motivo=motivo, roles_present=roles_present))


class AdminPanelView(discord.ui.View):
    def __init__(self, cog: "AdminPanelCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(label="Exonerar", style=discord.ButtonStyle.danger, emoji="📤", custom_id="adminpanel:exonerar", row=0)
    async def exonerar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(ExonerarAdminModal(self.cog, kind="EXONERAR"))

    @discord.ui.button(label="Desligamento", style=discord.ButtonStyle.danger, emoji="🚪", custom_id="adminpanel:desligamento", row=0)
    async def desligamento(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(ExonerarAdminModal(self.cog, kind="DESLIGAMENTO"))

    @discord.ui.button(label="Alinhar Membro", style=discord.ButtonStyle.primary, emoji="🧭", custom_id="adminpanel:alinhar", row=1)
    async def alinhar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(AlinharAdminModal(self.cog))

    @discord.ui.button(label="ADV", style=discord.ButtonStyle.secondary, emoji="⚠️", custom_id="adminpanel:adv", row=1)
    async def adv(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_message("Selecione o tipo de advertência:", view=AdvSelectView(self.cog), ephemeral=True)

    @discord.ui.button(label="Revogar Punição", style=discord.ButtonStyle.secondary, emoji="♻️", custom_id="adminpanel:revogar", row=1)
    async def revogar_punicao(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(RevogarPuniModal(self.cog))

    @discord.ui.button(label="Anúncio", style=discord.ButtonStyle.success, emoji="📣", custom_id="adminpanel:anuncio", row=2)
    async def anuncio(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, _get_admin_role_ids(cfg)):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(AnuncioAdminModal(self.cog))


class AdminPanelCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def kick_member(self, guild: discord.Guild, target_id: int, reason: str) -> tuple[bool, str]:
        """Tenta expulsar um membro. Retorna (ok, detail)."""
        try:
            member = guild.get_member(target_id)
            if not member:
                try:
                    member = await guild.fetch_member(target_id)
                except discord.NotFound:
                    return False, "ID não está no servidor"
            if not member:
                return False, "ID não está no servidor"
            await member.kick(reason=reason)
            return True, "OK"
        except discord.Forbidden:
            return False, "Forbidden (permissão/hierarquia)"
        except Exception as e:
            return False, f"Erro: {type(e).__name__}"

    async def notify_user(self, user_id: int, content: str):
        try:
            user = await self.bot.fetch_user(int(user_id))
            await user.send(content)
        except Exception:
            pass

    @app_commands.command(name="setup_admin_panel", description="Cria/atualiza o painel de ADM")
    async def setup_admin_panel(self, interaction: discord.Interaction):
        cfg = load_config()
        admin_ids = _get_admin_role_ids(cfg)
        if not is_admin_member(interaction.user, admin_ids):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        ch_id = int(cfg.get("admin_panel", {}).get("panel_channel_id", 0))
        if ch_id == 0:
            return await interaction.followup.send("❌ Configure `admin_panel.panel_channel_id` no config.json.", ephemeral=True)

        try:
            ch = await interaction.guild.fetch_channel(ch_id)
        except Exception:
            ch = None
        if not isinstance(ch, discord.TextChannel):
            return await interaction.followup.send("❌ Canal do painel ADM inválido.", ephemeral=True)

        embed = discord.Embed(
            title="🛡️ Painel Administrativo",
            description=(
                "Use os botões abaixo para ações administrativas.\n\n"
                "• **Exonerar / Desligamento**: remove um membro do Discord e registra em #exonerados\n"
                "• **Alinhar Membro**: abre ticket com o alvo e envia aviso no PV (24h)\n"
                "• **ADV**: aplica uma advertência, envia no canal de punição e adiciona o cargo correspondente\n"
                "• **Revogar Punição**: remove uma ADV (cargo), envia no canal de punição e avisa no PV\n"
                "• **Anúncio**: envia um anúncio marcando @everyone"
            ),
            color=discord.Color.dark_teal(),
        )
        embed.set_footer(text="Ações restritas a ADM")

        panel_message_id = int(cfg.get("admin_panel", {}).get("panel_message_id", 0))
        msg = None
        if panel_message_id:
            try:
                msg = await ch.fetch_message(panel_message_id)
            except Exception:
                msg = None

        if msg:
            await msg.edit(embed=embed, view=AdminPanelView(self))
        else:
            msg = await ch.send(embed=embed, view=AdminPanelView(self))
            try:
                await msg.pin(reason="Painel ADM")
            except Exception:
                pass
            cfg.setdefault("admin_panel", {})
            cfg["admin_panel"]["panel_message_id"] = msg.id
            save_config(cfg)

        await interaction.followup.send(f"✅ Painel de ADM pronto em {ch.mention}.", ephemeral=True)


async def setup(bot: commands.Bot):
    cog = AdminPanelCog(bot)
    bot.add_view(AdminPanelView(cog))
    await bot.add_cog(cog)
