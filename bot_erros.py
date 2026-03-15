import discord
from discord.ext import commands
import pytesseract
from PIL import Image
import sqlite3
import io
from rapidfuzz import fuzz

# Caminho do Tesseract ---------------------------------------------------------------------------------------------------------------------------------------
pytesseract.pytesseract.tesseract_cmd = r"C:\Program Files\Tesseract-OCR\tesseract.exe"

# BANCO DE DADOS ---------------------------------------------------------------------------------------------------------------------------------------
conn = sqlite3.connect("prints.db")
cur = conn.cursor()

cur.execute("""
CREATE TABLE IF NOT EXISTS images (
    message_id TEXT PRIMARY KEY,
    channel_id TEXT,
    user_id TEXT,
    text_content TEXT
)
""")
conn.commit()

# CONFIG DO BOT ---------------------------------------------------------------------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True
intents.members = True

bot = commands.Bot(command_prefix="!", intents=intents)

# FUNÇÃO OCR ---------------------------------------------------------------------------------------------------------------------------------------
async def ocr_do_anexo(arquivo):
    try:
        dados = await arquivo.read()
        img = Image.open(io.BytesIO(dados))
        texto = pytesseract.image_to_string(img, lang="por")
        return texto.strip()
    except Exception as err:
        print("Erro OCR:", err)
        return ""

# PEGAR NOVOS PRINTS AUTOMATICAMENTE -----------------------------------------------------------------------------------------------------------------------------------
@bot.event
async def on_message(msg):

    if msg.author.bot:
        return await bot.process_commands(msg)

    if not msg.attachments:
        return await bot.process_commands(msg)

    for arq in msg.attachments:

        if not arq.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            continue

        texto = await ocr_do_anexo(arq)

        if not texto.strip():
            continue

        cur.execute("""
            INSERT OR REPLACE INTO images (message_id, channel_id, user_id, text_content)
            VALUES (?, ?, ?, ?)
        """, (str(msg.id), str(msg.channel.id), str(msg.author.id), texto))
        conn.commit()

    await bot.process_commands(msg)

# COMANDO BUSCAR ---------------------------------------------------------------------------------------------------------------------------------------
@bot.command()
async def buscar(ctx, *, termo):
    cur.execute("SELECT message_id, channel_id, text_content FROM images")
    dados = cur.fetchall()

    encontrados = []
    termo_lower = termo.lower()

    for msg_id, canal_id, texto in dados:

        score = fuzz.partial_ratio(termo_lower, texto.lower())

        if score >= 60:
            encontrados.append((msg_id, canal_id, score))

    if not encontrados:
        await ctx.send("❌ Nenhum print encontrado.")
        return

    encontrados.sort(key=lambda x: x[2], reverse=True)

    resp = " **🔎 Resultados:**\n\n"

    for msg_id, canal_id, score in encontrados[:5]:

        canal = bot.get_channel(int(canal_id))

        if canal is None:
            continue

        try:
            msg = await canal.fetch_message(int(msg_id))
            data = msg.created_at.strftime("%d/%m/%Y")  # Só a data
        except:
            data = "Data indisponível"

        link = f"https://discord.com/channels/{ctx.guild.id}/{canal_id}/{msg_id}"
        resp += f"• **{score:.2f}%** → {link} — `{data}`\n"

    await ctx.send(resp)


# CONTAS QUANTAS MSG TEM ------------------------------------------------------------------------------------------------------------------------------------

@bot.command()
async def contarmensagens(ctx, canal_id: int, limite: int = None):
    canal = bot.get_channel(canal_id)

    if canal is None:
        await ctx.send("Canal inválido.")
        return

    total = 0
    msg_status = await ctx.send(f"Contando... {canal.mention}...")

    try:
        async for _ in canal.history(limit=limite):
            total += 1
    except Exception:
        await ctx.send("❌ Não foi possível acessar o histórico do canal.")
        return

    await msg_status.edit(content=f"O canal {canal.mention} tem **{total}** mensagens.")



# INDEXAR TODOS OS CANAIS ---------------------------------------------------------------------------------------------------------------------------------------


@bot.command()

async def indexar(ctx, limite: int = None):

    if limite is None:
        status = await ctx.send("🔄 Indexando **todas as mensagens** de todos os canais...\n Total de prints processados: **0**")
    else:
        status = await ctx.send(f"🔄 Indexando **{limite} mensagens** de cada canal...\n Total de prints processados: **0**")

    total = 0

    for canal in ctx.guild.text_channels:
        try:
            async for msg in canal.history(limit=limite):

                if msg.attachments:
                    for arq in msg.attachments:

                        if arq.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):

                            texto = await ocr_do_anexo(arq)

                            cur.execute("""
                                INSERT OR REPLACE INTO images (message_id, channel_id, user_id, text_content)
                                VALUES (?, ?, ?, ?)
                            """, (str(msg.id), str(canal.id), str(msg.author.id), texto))
                            conn.commit()

                            total += 1

                            #  Edita mensagem a cada 20 prints
                            if total % 20 == 0:
                                await status.edit(content=f"🔄 Indexando...\n Total de prints processados: **{total}**")

        except Exception:
            pass

    await status.edit(content=f" Finalizado! Foram processados **{total}** prints.")


# INDEXAR UM CANAL ESPECÍFICO ---------------------------------------------------------------------------------------------------------------------------------------


@bot.command()

async def indexarcanal(ctx, canal_id: int, limite: int = None):

    canal = bot.get_channel(canal_id)

    if canal is None:
        await ctx.send(" Canal inválido.")
        return

    if limite is None:
        status = await ctx.send(f"🔄 Indexando todas mensagens de <#{canal_id}>...\n📸 Total de prints processados: **0**")
    else:
        status = await ctx.send(f"🔄 Indexando {limite} mensagens de <#{canal_id}>...\n📸 Total de prints processados: **0**")

    total = 0

    try:
        async for msg in canal.history(limit=limite):

            if msg.attachments:
                for arq in msg.attachments:

                    if arq.filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp")):

                        texto = await ocr_do_anexo(arq)

                        cur.execute("""
                            INSERT OR REPLACE INTO images (message_id, channel_id, user_id, text_content)
                            VALUES (?, ?, ?, ?)
                        """, (str(msg.id), str(canal.id), str(msg.author.id), texto))
                        conn.commit()

                        total += 1

                       
                        if total % 20 == 0:
                            await status.edit(content=f"🔄 Indexando...\n📸 Total de prints processados: **{total}**")

    except Exception:
        await ctx.send("❌ Erro ao acessar o canal.")
        return

    await status.edit(content=f" Finalizado! Foram processados **{total}** prints.")


# INICIA BOT
bot.run("")
