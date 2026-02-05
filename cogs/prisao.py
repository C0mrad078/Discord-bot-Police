from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Optional, List, Dict

import discord
from discord.ext import commands, tasks
from discord import app_commands

from utils.config import load_config, save_config
from utils.perm import is_admin_member
from utils.timeutils import utcnow, parse_iso, start_of_day, start_of_week, start_of_month, start_of_year



def _pack_record(d: dict) -> str:
    return "```json\n" + json.dumps(d, ensure_ascii=False) + "\n```"


def _unpack_record(content: str) -> Optional[dict]:
    content = (content or "").strip()
    if content.startswith("```json"):
        content = content[len("```json"):].strip()
    if content.startswith("```"):
        content = content[3:].strip()
    if content.endswith("```"):
        content = content[:-3].strip()
    try:
        return json.loads(content)
    except Exception:
        return None


async def fetch_all_prison_records(db_channel: discord.TextChannel, limit: int = 2000) -> List[dict]:
    records: List[dict] = []
    async for msg in db_channel.history(limit=limit, oldest_first=True):
        rec = _unpack_record(msg.content)
        if rec and rec.get("type") == "prisao":
            rec["_db_msg_id"] = msg.id
            records.append(rec)
    return records


async def delete_record_message(db_channel: discord.TextChannel, msg_id: int) -> None:
    try:
        msg = await db_channel.fetch_message(msg_id)
        await msg.delete()
    except Exception:
        pass


# =====================
# UI
# =====================
class PrisaoModal(discord.ui.Modal, title="Registro de Prisão"):
    preso_id = discord.ui.TextInput(label="ID do Preso", required=True, placeholder="Ex: 12345")
    preso_nome = discord.ui.TextInput(label="Nome do Preso", required=True, placeholder="Ex: João Silva")
    tempo = discord.ui.TextInput(label="Tempo de Prisão (SERVIÇOS)", required=True, placeholder="Ex: 30")
    multa = discord.ui.TextInput(label="Multa (somente números)", required=True, placeholder="Ex: 25000")
    registro = discord.ui.TextInput(label="Registro / Ocorrência", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, cog: "PrisaoCog"):
        super().__init__(timeout=300)
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.handle_prisao_submit(
            interaction,
            {
                "preso_id": str(self.preso_id.value).strip(),
                "preso_nome": str(self.preso_nome.value).strip(),
                "tempo": str(self.tempo.value).strip(),
                "multa": str(self.multa.value).strip(),
                "registro": str(self.registro.value).strip(),
            },
        )


class PrisaoPanelView(discord.ui.View):
    def __init__(self, cog: "PrisaoCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Registrar Prisão",
        style=discord.ButtonStyle.danger,
        emoji="📝",
        custom_id="prisao:registrar",
    )
    async def registrar(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PrisaoModal(self.cog))


class ReprovarPrisaoModal(discord.ui.Modal, title="Reprovar Prisão"):
    motivo = discord.ui.TextInput(label="Motivo", style=discord.TextStyle.paragraph, required=True)

    def __init__(self, cog: "PrisaoCog", db_msg_id: int, registro_msg_id: int):
        super().__init__(timeout=240)
        self.cog = cog
        self.db_msg_id = db_msg_id
        self.registro_msg_id = registro_msg_id

    async def on_submit(self, interaction: discord.Interaction):
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog.handle_reprovar_prisao(
            interaction,
            db_msg_id=self.db_msg_id,
            registro_msg_id=self.registro_msg_id,
            motivo=str(self.motivo.value).strip(),
        )


class PrisaoAdmView(discord.ui.View):
    def __init__(self, cog: "PrisaoCog", db_msg_id: int, registro_msg_id: int):
        super().__init__(timeout=None)
        self.cog = cog
        self.db_msg_id = db_msg_id
        self.registro_msg_id = registro_msg_id

    @discord.ui.button(
        label="Reprovar Prisão",
        style=discord.ButtonStyle.danger,
        emoji="⛔",
        custom_id="prisao:reprovar",
    )
    async def reprovar(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["prison"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        await interaction.response.send_modal(ReprovarPrisaoModal(self.cog, self.db_msg_id, self.registro_msg_id))


class PrisaoRankView(discord.ui.View):
    def __init__(self, cog: "PrisaoCog"):
        super().__init__(timeout=None)
        self.cog = cog

    @discord.ui.button(
        label="Atualizar agora",
        style=discord.ButtonStyle.secondary,
        emoji="🔄",
        custom_id="prisao:rank_refresh",
    )
    async def refresh(self, interaction: discord.Interaction, button: discord.ui.Button):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["prison"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)
        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass
        await self.cog._rank_loop_body()
        await interaction.followup.send("✅ Ranking atualizado.", ephemeral=True)


# =====================
# COG
# =====================
class PrisaoCog(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.rank_loop.start()

    def cog_unload(self):
        try:
            self.rank_loop.cancel()
        except Exception:
            pass

    # ----------
    # Setup painel
    # ----------
    @app_commands.command(name="setup_prisao", description="Cria/atualiza o painel de prisão.")
    async def setup_prisao(self, interaction: discord.Interaction):
        cfg = load_config()
        ch_id = cfg["prison"]["channel_realizar_prisao_id"]
        ch = await interaction.guild.fetch_channel(ch_id)
        if not isinstance(ch, discord.TextChannel):
            return await interaction.response.send_message("Canal de painel de prisão inválido no config.json.", ephemeral=True)

        embed = discord.Embed(
            title="🚓 Registro de Prisão – Sistema Oficial",
            description=(
                "**Todos os campos são obrigatórios.**\n\n"
                "📌 **TODOS os alunos e soldados são obrigados a registrar a prisão.**\n\n"
                "🕒 Prisão é definida por **SERVIÇOS** (ex: `30` serviços).\n"
                "💰 Multa obrigatória (**somente números**).\n"
                "📝 Descreva bem a ocorrência no campo **Registro**.\n\n"
                "Clique em **📝 Registrar Prisão** para iniciar."
            ),
            color=discord.Color.red(),
        )
        embed.set_footer(text="Hype Police • Sistema de Prisões")

        view = PrisaoPanelView(self)

        panel_msg_id = int(cfg["prison"].get("panel_message_id", 0) or 0)
        msg = None
        if panel_msg_id:
            try:
                msg = await ch.fetch_message(panel_msg_id)
                await msg.edit(embed=embed, view=view)
            except Exception:
                msg = None

        if msg is None:
            msg = await ch.send(embed=embed, view=view)
            try:
                await msg.pin()
            except Exception:
                pass
            cfg["prison"]["panel_message_id"] = msg.id
            save_config(cfg)

        await interaction.response.send_message("✅ Painel de prisão pronto.", ephemeral=True)

    # ----------
    # Registro de prisão
    # ----------
    async def handle_prisao_submit(self, interaction: discord.Interaction, data: dict):
        cfg = load_config()

        if not data["tempo"].isdigit():
            return await interaction.followup.send("❌ Tempo deve ser número (SERVIÇOS).", ephemeral=True)
        if not data["multa"].isdigit():
            return await interaction.followup.send("❌ Multa deve ser apenas números.", ephemeral=True)

        guild = interaction.guild
        reg_ch = await guild.fetch_channel(cfg["prison"]["channel_registro_prisoes_id"])
        adm_ch = await guild.fetch_channel(cfg["prison"]["channel_prisao_adm_id"])
        db_ch = await guild.fetch_channel(cfg["prison"]["channel_db_prisao_id"])

        if not isinstance(reg_ch, discord.TextChannel) or not isinstance(adm_ch, discord.TextChannel) or not isinstance(db_ch, discord.TextChannel):
            return await interaction.followup.send("❌ Configuração de canais de prisão inválida.", ephemeral=True)

        embed = discord.Embed(title="📄 Prisão Registrada", color=discord.Color.orange(), timestamp=utcnow())
        embed.add_field(name="Preso", value=f"**{data['preso_nome']}** (ID `{data['preso_id']}`)", inline=False)
        embed.add_field(name="Tempo", value=f"`{data['tempo']}` serviços", inline=True)
        embed.add_field(name="Multa", value=f"`{data['multa']}`", inline=True)
        embed.add_field(name="Registro", value=data["registro"][:1000], inline=False)
        embed.set_footer(text=f"Registrado por {interaction.user} • ID {interaction.user.id}")

        registro_msg = await reg_ch.send(embed=embed)

        record = {
            "type": "prisao",
            "ts": utcnow().isoformat(),
            "officer_id": interaction.user.id,
            "officer_tag": str(interaction.user),
            "preso_id": data["preso_id"],
            "preso_nome": data["preso_nome"],
            "tempo": int(data["tempo"]),
            "multa": int(data["multa"]),
            "registro": data["registro"],
            "registro_channel_id": reg_ch.id,
            "registro_message_id": registro_msg.id,
        }
        db_msg = await db_ch.send(_pack_record(record))

        adm_embed = embed.copy()
        adm_embed.title = "🛡️ Prisão para Revisão (ADM)"
        adm_embed.color = discord.Color.red()
        adm_embed.add_field(name="Ação", value="Use **⛔ Reprovar Prisão** se houver erro/abuso.", inline=False)
        adm_embed.set_footer(text=f"DB Msg ID: {db_msg.id} • Registro Msg ID: {registro_msg.id}")

        await adm_ch.send(embed=adm_embed, view=PrisaoAdmView(self, db_msg.id, registro_msg.id))

        try:
            await interaction.user.send(embed=embed)
        except Exception:
            pass

        await interaction.followup.send("✅ Prisão registrada com sucesso.", ephemeral=True)

    # ----------
    # Revogar/Reprovar prisão (ADM)
    # ----------
    async def handle_reprovar_prisao(self, interaction: discord.Interaction, db_msg_id: int, registro_msg_id: int, motivo: str):
        cfg = load_config()
        guild = interaction.guild

        reg_ch = await guild.fetch_channel(cfg["prison"]["channel_registro_prisoes_id"])
        db_ch = await guild.fetch_channel(cfg["prison"]["channel_db_prisao_id"])

        if not isinstance(reg_ch, discord.TextChannel) or not isinstance(db_ch, discord.TextChannel):
            return await interaction.followup.send("❌ Configuração de canais inválida.", ephemeral=True)

        # 1) Puxa o registro do DB antes de apagar
        record = None
        try:
            db_msg = await db_ch.fetch_message(db_msg_id)
            record = _unpack_record(db_msg.content)
        except Exception:
            record = None

        # 2) Remove do registro público (mensagem original)
        try:
            msg = await reg_ch.fetch_message(registro_msg_id)
            await msg.delete()
        except Exception:
            pass

        # 3) Remove do DB
        await delete_record_message(db_ch, db_msg_id)

        # 4) Publica aviso completo no canal de registro + DM no policial
        if record:
            preso_nome = record.get("preso_nome", "—")
            preso_id = record.get("preso_id", "—")
            tempo = record.get("tempo", "—")
            multa = record.get("multa", "—")
            registro_txt = str(record.get("registro", "—"))
            officer_id = int(record.get("officer_id", 0) or 0)
            ts_iso = str(record.get("ts", ""))
            try:
                ts = parse_iso(ts_iso)
            except Exception:
                ts = utcnow()

            embed = discord.Embed(
                title="⚠️ Prisão revogada",
                description=f"**Motivo:** {motivo}\n**Revogado por:** {interaction.user.mention}",
                color=discord.Color.red(),
                timestamp=ts,
            )
            embed.add_field(name="Preso", value=f"**{preso_nome}** (ID `{preso_id}`)", inline=False)
            embed.add_field(name="Tempo", value=f"`{tempo}` serviços", inline=True)
            embed.add_field(name="Multa", value=f"`{multa}`", inline=True)
            embed.add_field(name="Registro", value=registro_txt[:1000], inline=False)
            embed.set_footer(text=f"DB Msg ID: {db_msg_id}")

            await reg_ch.send(embed=embed)

            if officer_id:
                try:
                    officer = await self.bot.fetch_user(officer_id)
                    dm_embed = embed.copy()
                    dm_embed.title = "⛔ Sua prisão foi revogada"
                    await officer.send(embed=dm_embed)
                except Exception:
                    pass
        else:
            await reg_ch.send(f"⚠️ Uma prisão foi revogada por um ADM. Motivo: {motivo}")

        await interaction.followup.send("✅ Prisão revogada e notificada.", ephemeral=True)

    # ----------
    # Relatório por período
    # ----------
    def _parse_user_datetime(self, s: str) -> datetime:
        """Aceita: YYYY-MM-DD, DD/MM/YYYY, ou ISO (com hora). Retorna datetime timezone-aware (UTC)."""
        s = (s or '').strip()
        if not s:
            raise ValueError('data vazia')

        # ISO (com ou sem Z)
        try:
            dt = parse_iso(s)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass

        # YYYY-MM-DD
        m = re.match(r'^(\d{4})-(\d{2})-(\d{2})$', s)
        if m:
            y, mo, d = map(int, m.groups())
            return datetime(y, mo, d, tzinfo=timezone.utc)

        # DD/MM/YYYY
        m = re.match(r'^(\d{2})/(\d{2})/(\d{4})$', s)
        if m:
            d, mo, y = map(int, m.groups())
            return datetime(y, mo, d, tzinfo=timezone.utc)

        raise ValueError('formato inválido')

    @app_commands.command(name="relatorio_periodo", description="Relatório de prisões por período (usa o DB).")
    @app_commands.describe(inicio="Ex: 2026-01-01 ou 01/01/2026", fim="Ex: 2026-01-19 ou 19/01/2026")
    async def relatorio_periodo(self, interaction: discord.Interaction, inicio: str, fim: str):
        cfg = load_config()
        if not is_admin_member(interaction.user, cfg["prison"]["admin_role_ids"]):
            return await interaction.response.send_message("Apenas ADM.", ephemeral=True)

        try:
            ini_dt = self._parse_user_datetime(inicio)
            end_dt = self._parse_user_datetime(fim)
        except Exception:
            return await interaction.response.send_message(
                "❌ Formato de data inválido. Use `YYYY-MM-DD` ou `DD/MM/YYYY` (ex: `2026-01-01` / `01/01/2026`).",
                ephemeral=True,
            )

        # Se o usuário passar só data (sem hora), interpretamos como período do dia inteiro
        # - inicio: 00:00 UTC
        # - fim: até 23:59:59 UTC (fazendo +1 dia e usando <)
        ini_has_time = ('T' in inicio) or (':' in inicio)
        fim_has_time = ('T' in fim) or (':' in fim)
        if not ini_has_time:
            ini_dt = start_of_day(ini_dt)
        if not fim_has_time:
            end_dt = start_of_day(end_dt) + timedelta(days=1)
        else:
            end_dt = end_dt + timedelta(microseconds=1)

        if end_dt < ini_dt:
            return await interaction.response.send_message("❌ O `fim` precisa ser maior ou igual ao `inicio`.", ephemeral=True)

        try:
            await interaction.response.defer(ephemeral=True)
        except Exception:
            pass

        guild = interaction.guild
        try:
            db_ch = await guild.fetch_channel(cfg["prison"]["channel_db_prisao_id"])
        except Exception:
            db_ch = None

        if not isinstance(db_ch, discord.TextChannel):
            return await interaction.followup.send("❌ Canal de DB de prisão inválido no config.json.", ephemeral=True)

        records = await fetch_all_prison_records(db_ch, limit=4000)

        filtered = []
        for r in records:
            try:
                ts = parse_iso(str(r.get('ts', '')))
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                ts = ts.astimezone(timezone.utc)
            except Exception:
                continue
            if ini_dt <= ts < end_dt:
                filtered.append(r)

        total = len(filtered)
        if total == 0:
            return await interaction.followup.send("📭 Nenhuma prisão encontrada nesse período.", ephemeral=True)

        # agrega
        by_officer: dict[int, int] = {}
        total_tempo = 0
        total_multa = 0
        for r in filtered:
            oid = int(r.get('officer_id', 0) or 0)
            if oid:
                by_officer[oid] = by_officer.get(oid, 0) + 1
            try:
                total_tempo += int(r.get('tempo', 0) or 0)
            except Exception:
                pass
            try:
                total_multa += int(r.get('multa', 0) or 0)
            except Exception:
                pass

        top = sorted(by_officer.items(), key=lambda x: x[1], reverse=True)[:15]
        top_lines = "\n".join([f"`{i+1:02d}.` <@{uid}> — **{cnt}**" for i, (uid, cnt) in enumerate(top)]) or "_Sem dados_"

        # Texto do período (mantém o que o usuário digitou, mas com datas calculadas)
        # Mostra intervalo em UTC pra não ter confusão.
        periodo_txt = f"{ini_dt.strftime('%Y-%m-%d %H:%M UTC')}  →  {(end_dt - timedelta(microseconds=1)).strftime('%Y-%m-%d %H:%M UTC')}"

        embed = discord.Embed(title="📊 Relatório de Prisões (Período)", color=discord.Color.blurple(), timestamp=utcnow())
        embed.add_field(name="Período", value=periodo_txt, inline=False)
        embed.add_field(name="Total de prisões", value=f"**{total}**", inline=True)
        embed.add_field(name="Tempo total (serviços)", value=f"**{total_tempo}**", inline=True)
        embed.add_field(name="Multa total", value=f"**{total_multa}**", inline=True)
        embed.add_field(name="Top policiais", value=top_lines[:1024], inline=False)
        embed.set_footer(text="Hype Police • Relatórios")

        await interaction.followup.send(embed=embed, ephemeral=True)

    # ----------
    # Ranking
    # ----------
    def _build_rank_embed(self, buckets: Dict[str, Dict[int, int]]) -> discord.Embed:
        embed = discord.Embed(title="🏆 Ranking de Prisões", color=discord.Color.gold(), timestamp=utcnow())
        embed.description = "Atualiza automaticamente a cada **1 minuto**."
        for key, title in [("day", "Hoje"), ("week", "Semana"), ("month", "Mês"), ("year", "Ano")]:
            data = buckets.get(key, {})
            if not data:
                value = "_Sem registros._"
            else:
                items = sorted(data.items(), key=lambda x: x[1], reverse=True)[:10]
                value = "\n".join([f"`{i+1:02d}.` <@{uid}> — **{count}**" for i, (uid, count) in enumerate(items)])
            embed.add_field(name=title, value=value, inline=False)
        embed.set_footer(text="Hype Police • Ranking")
        return embed

    def _calc_buckets(self, records: List[dict]) -> Dict[str, Dict[int, int]]:
        now = utcnow()
        day0 = start_of_day(now)
        week0 = start_of_week(now)
        month0 = start_of_month(now)
        year0 = start_of_year(now)

        buckets: Dict[str, Dict[int, int]] = {"day": {}, "week": {}, "month": {}, "year": {}}

        for r in records:
            try:
                ts = parse_iso(str(r.get("ts", "")))
            except Exception:
                ts = now
            officer_id = int(r.get("officer_id", 0) or 0)
            if not officer_id:
                continue

            def inc(bucket: str):
                buckets[bucket][officer_id] = buckets[bucket].get(officer_id, 0) + 1

            if ts >= year0:
                inc("year")
            if ts >= month0:
                inc("month")
            if ts >= week0:
                inc("week")
            if ts >= day0:
                inc("day")

        return buckets

    async def _rank_loop_body(self):
        cfg = load_config()
        guild = self.bot.get_guild(cfg["guild_id"])
        if not guild:
            return

        try:
            rank_ch = await guild.fetch_channel(cfg["prison"]["channel_rank_id"])
            db_ch = await guild.fetch_channel(cfg["prison"]["channel_db_prisao_id"])
        except Exception:
            return
        if not isinstance(rank_ch, discord.TextChannel) or not isinstance(db_ch, discord.TextChannel):
            return

        records = await fetch_all_prison_records(db_ch, limit=2000)
        buckets = self._calc_buckets(records)
        embed = self._build_rank_embed(buckets)

        msg_id = int(cfg["prison"].get("rank_message_id", 0) or 0)
        msg = None
        if msg_id:
            try:
                msg = await rank_ch.fetch_message(msg_id)
                await msg.edit(embed=embed, view=PrisaoRankView(self))
            except Exception:
                msg = None
        if msg is None:
            try:
                msg = await rank_ch.send(embed=embed, view=PrisaoRankView(self))
                try:
                    await msg.pin(reason="Ranking de prisões")
                except Exception:
                    pass
                cfg["prison"]["rank_message_id"] = msg.id
                save_config(cfg)
            except Exception:
                pass

    @tasks.loop(minutes=1)
    async def rank_loop(self):
        await self._rank_loop_body()


async def setup(bot: commands.Bot):
    cog = PrisaoCog(bot)
    bot.add_view(PrisaoPanelView(cog))
    bot.add_view(PrisaoRankView(cog))
    await bot.add_cog(cog)
