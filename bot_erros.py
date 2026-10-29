import asyncio
import io
import os
import re
import sqlite3
import time
import traceback
import unicodedata
from datetime import datetime
from pathlib import Path
from typing import Union

import discord
from discord.ext import commands
import pytesseract
from PIL import Image
from rapidfuzz import fuzz, process

import relatorios  # busca nos relatórios e exportações do SPICA (catálogo gerado pelo catalogo_relatorios.py)
import mapa_menus  # print do menu do SPICA com a tela circulada em vermelho (índice gerado pelo mapa_menus.py)

PASTA = Path(__file__).resolve().parent

# CONFIG ---------------------------------------------------------------------------------------------------------------------------------------
# Lê o arquivo .env ao lado do bot (DISCORD_TOKEN=..., TESSERACT_CMD=..., OCR_LANG=...)
def carregar_env():
    arquivo = PASTA / ".env"
    if not arquivo.exists():
        return
    for linha in arquivo.read_text(encoding="utf-8-sig").splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, valor = linha.split("=", 1)
        os.environ.setdefault(chave.strip(), valor.strip().strip('"').strip("'"))


carregar_env()

TOKEN = os.environ.get("DISCORD_TOKEN", "")
pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
OCR_LANG = os.environ.get("OCR_LANG", "por")
DB_PATH = PASTA / "prints.db"

EXTENSOES = (".png", ".jpg", ".jpeg", ".bmp", ".webp")
NOTA_MINIMA = 60
MAX_RESULTADOS = 5
EMOJI_SOLUCAO = "✅"
EMOJI_SALVO = "💾"
ANEXO_ANTIGO = "antigo"  # registros do banco antigo, que não guardava o id do anexo
OCR_VERSAO = 2  # 1 = OCR sem ampliar a imagem; 2 = OCR com ampliação. Aumente se o OCR mudar de novo e rode !reocr

# TEXTO ---------------------------------------------------------------------------------------------------------------------------------------
def limpar(texto):
    return unicodedata.normalize("NFC", texto or "").strip()


# Minúsculo, sem acento e sem quebra de linha, mantendo o mesmo tamanho do texto original:
# assim a posição encontrada na busca serve para recortar o trecho do texto original.
def normalizar(texto):
    saida = []
    for ch in texto:
        if ch.isspace():
            saida.append(" ")
        else:
            saida.append(unicodedata.normalize("NFKD", ch.lower()[0])[0])
    return "".join(saida)


def recortar_trecho(texto, texto_norm, termo_norm, tamanho=200):
    alinhamento = fuzz.partial_ratio_alignment(termo_norm, texto_norm)
    inicio, fim = (alinhamento.dest_start, alinhamento.dest_end) if alinhamento else (0, 0)
    folga = max(0, (tamanho - (fim - inicio)) // 2)
    ini = max(0, inicio - folga)
    fim = min(len(texto), fim + folga)
    trecho = " ".join(texto[ini:fim].split()).replace("`", "'")
    if ini > 0:
        trecho = "…" + trecho
    if fim < len(texto):
        trecho += "…"
    return trecho[: tamanho + 50]


def data_da_mensagem(message_id):
    return discord.utils.snowflake_time(int(message_id)).astimezone().strftime("%d/%m/%Y")


# BANCO DE DADOS ---------------------------------------------------------------------------------------------------------------------------------------
conn = sqlite3.connect(DB_PATH)
cur = conn.cursor()


def criar_tabelas():
    cur.execute("""
    CREATE TABLE IF NOT EXISTS images (
        message_id TEXT NOT NULL,
        attachment_id TEXT NOT NULL,
        channel_id TEXT,
        guild_id TEXT,
        user_id TEXT,
        text_content TEXT,
        text_norm TEXT,
        ocr_versao INTEGER NOT NULL DEFAULT 1,
        PRIMARY KEY (message_id, attachment_id)
    )
    """)
    cur.execute("""
    CREATE TABLE IF NOT EXISTS solucoes (
        print_message_id TEXT NOT NULL,
        solucao_message_id TEXT NOT NULL,
        channel_id TEXT,
        autor_id TEXT,
        texto TEXT,
        origem TEXT,
        PRIMARY KEY (print_message_id, solucao_message_id)
    )
    """)
    conn.commit()


# Converte o banco da versão antiga (1 linha por mensagem) para o novo formato, com backup antes
def migrar_banco():
    colunas = [c[1] for c in cur.execute("PRAGMA table_info(images)")]
    if not colunas or "attachment_id" in colunas:
        return

    backup = DB_PATH.with_name(f"prints_backup_{datetime.now():%Y%m%d_%H%M%S}.db")
    with sqlite3.connect(backup) as destino:
        conn.backup(destino)
    print(f"Backup do banco antigo salvo em {backup.name}")

    cur.execute("ALTER TABLE images RENAME TO images_antiga")
    criar_tabelas()
    antigas = cur.execute("SELECT message_id, channel_id, user_id, text_content FROM images_antiga").fetchall()
    novas = []
    for message_id, channel_id, user_id, texto in antigas:
        texto = limpar(texto)
        novas.append((message_id, ANEXO_ANTIGO, channel_id, None, user_id, texto, normalizar(texto)))
    cur.executemany("""
        INSERT OR REPLACE INTO images (message_id, attachment_id, channel_id, guild_id, user_id, text_content, text_norm)
        VALUES (?, ?, ?, ?, ?, ?, ?)
    """, novas)
    cur.execute("DROP TABLE images_antiga")
    conn.commit()
    cur.execute("VACUUM")
    print(f"Banco migrado: {len(novas)} prints convertidos.")


def garantir_colunas():
    colunas = [c[1] for c in cur.execute("PRAGMA table_info(images)")]
    if "ocr_versao" not in colunas:
        cur.execute("ALTER TABLE images ADD COLUMN ocr_versao INTEGER NOT NULL DEFAULT 1")
        conn.commit()


migrar_banco()
criar_tabelas()
garantir_colunas()


def tem_print(message_id):
    return cur.execute("SELECT 1 FROM images WHERE message_id = ? LIMIT 1", (str(message_id),)).fetchone() is not None


def salvar_solucao(print_message_id, msg, texto, origem):
    cur.execute("""
        INSERT OR REPLACE INTO solucoes (print_message_id, solucao_message_id, channel_id, autor_id, texto, origem)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (str(print_message_id), str(msg.id), str(msg.channel.id), str(msg.author.id), texto, origem))
    conn.commit()


def apagar_mensagens(ids):
    for message_id in ids:
        message_id = str(message_id)
        cur.execute("DELETE FROM images WHERE message_id = ?", (message_id,))
        cur.execute("DELETE FROM solucoes WHERE print_message_id = ? OR solucao_message_id = ?", (message_id, message_id))
    conn.commit()


# CONFIG DO BOT ---------------------------------------------------------------------------------------------------------------------------------------
intents = discord.Intents.default()
intents.message_content = True

bot = commands.Bot(command_prefix="!", intents=intents, help_command=None)
indexacao_lock = asyncio.Lock()
relatorios_lock = asyncio.Lock()
catalogo = relatorios.Catalogo()


async def buscar_mensagem(canal_id, message_id):
    try:
        return await bot.get_partial_messageable(canal_id).fetch_message(message_id)
    except discord.HTTPException:
        return None


# FUNÇÃO OCR ---------------------------------------------------------------------------------------------------------------------------------------
# Roda numa thread separada para não travar o bot enquanto o Tesseract trabalha
def _ocr(dados):
    img = Image.open(io.BytesIO(dados))
    if img.width < 1600:  # prints pequenos: ampliar 2x melhora bastante o Tesseract (testado: pior caso de 68% para 84%)
        img = img.resize((img.width * 2, img.height * 2), Image.LANCZOS)
    return limpar(pytesseract.image_to_string(img, lang=OCR_LANG))


# Retorna None se deu erro (para tentar de novo depois) e "" se a imagem não tem texto
async def ocr_do_anexo(arquivo):
    try:
        dados = await arquivo.read()
        return await asyncio.to_thread(_ocr, dados)
    except Exception as err:
        print(f"Erro OCR ({arquivo.filename}):", err)
        return None


# INDEXAÇÃO ---------------------------------------------------------------------------------------------------------------------------------------
# Lê com OCR os prints da mensagem que ainda não estão no banco. Retorna quantos prints novos foram lidos.
# Com refazer=True lê de novo (OCR atual) os prints que já estavam no banco
async def indexar_mensagem(msg, refazer=False):
    imagens = [a for a in msg.attachments if a.filename.lower().endswith(EXTENSOES)]
    if not imagens:
        return 0

    message_id = str(msg.id)
    guild_id = str(msg.guild.id) if msg.guild else None
    existentes = {r[0] for r in cur.execute("SELECT attachment_id FROM images WHERE message_id = ?", (message_id,))}
    ja_indexados = set() if refazer else existentes

    # Registro do banco antigo: com 1 print só falta o id do anexo; com vários, só o último tinha sido salvo
    tinha_antigo = ANEXO_ANTIGO in existentes
    if tinha_antigo and len(imagens) == 1 and not refazer:
        cur.execute(
            "UPDATE images SET attachment_id = ?, guild_id = ? WHERE message_id = ? AND attachment_id = ?",
            (str(imagens[0].id), guild_id, message_id, ANEXO_ANTIGO),
        )
        return 0

    novos = 0
    for arq in imagens:
        if str(arq.id) in ja_indexados:
            continue

        texto = await ocr_do_anexo(arq)
        if texto is None:
            continue

        cur.execute("""
            INSERT OR REPLACE INTO images (message_id, attachment_id, channel_id, guild_id, user_id, text_content, text_norm, ocr_versao)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        """, (message_id, str(arq.id), str(msg.channel.id), guild_id, str(msg.author.id), texto, normalizar(texto), OCR_VERSAO))
        novos += 1

    if tinha_antigo and novos:
        cur.execute("DELETE FROM images WHERE message_id = ? AND attachment_id = ?", (message_id, ANEXO_ANTIGO))

    return novos


class Progresso:
    def __init__(self, status, titulo, rotulo="Prints novos lidos"):
        self.status = status
        self.titulo = titulo
        self.rotulo = rotulo
        self.mensagens = 0
        self.novos = 0
        self.apagados = 0
        self.erros = []
        self._ultima = time.monotonic()

    def texto(self, fim=False):
        cabecalho = "✅ Finalizado!" if fim else f"🔄 {self.titulo}"
        texto = (
            f"{cabecalho}\n"
            f"📨 Mensagens verificadas: **{self.mensagens}**\n"
            f"📸 {self.rotulo}: **{self.novos}**"
        )
        if self.apagados:
            texto += f"\n🗑️ Mensagens apagadas removidas do banco: **{self.apagados}**"
        if self.erros:
            texto += "\n⚠️ Sem acesso a: " + ", ".join(self.erros[:15])
        return texto

    async def atualizar(self, forcar=False, fim=False):
        if not forcar and time.monotonic() - self._ultima < 5:
            return
        self._ultima = time.monotonic()
        conn.commit()
        try:
            await self.status.edit(content=self.texto(fim))
        except discord.HTTPException:
            pass


# O canal em si (se tiver histórico) e todos os tópicos dele, abertos e arquivados
async def canal_e_topicos(canal):
    if not isinstance(canal, discord.ForumChannel):
        yield canal
    if isinstance(canal, discord.Thread):
        return
    for topico in canal.threads:
        yield topico
    try:
        async for topico in canal.archived_threads(limit=None):
            yield topico
    except discord.HTTPException:
        pass


async def indexar_canal(canal, limite, progresso):
    async for alvo in canal_e_topicos(canal):
        try:
            async for msg in alvo.history(limit=limite):
                progresso.mensagens += 1
                if msg.attachments and not msg.author.bot:
                    progresso.novos += await indexar_mensagem(msg)
                await progresso.atualizar()
        except discord.HTTPException as err:
            print(f"Sem acesso a #{alvo.name}:", err)
            progresso.erros.append(alvo.mention)


# EVENTOS ---------------------------------------------------------------------------------------------------------------------------------------
@bot.event
async def on_ready():
    # Completa o servidor dos registros antigos, usado para montar o link
    for (canal_id,) in cur.execute("SELECT DISTINCT channel_id FROM images WHERE guild_id IS NULL").fetchall():
        canal = bot.get_channel(int(canal_id))
        if canal is not None:
            cur.execute("UPDATE images SET guild_id = ? WHERE channel_id = ?", (str(canal.guild.id), canal_id))
    conn.commit()

    total = cur.execute("SELECT COUNT(*) FROM images").fetchone()[0]
    print(f"Bot conectado como {bot.user} — {total} prints no banco, {len(catalogo.rotinas)} telas de relatório no catálogo.")


# Pega novos prints automaticamente
@bot.event
async def on_message(msg):
    if msg.attachments and msg.guild and not msg.author.bot:
        await indexar_mensagem(msg)
        conn.commit()

    await bot.process_commands(msg)


@bot.event
async def on_raw_message_delete(payload):
    apagar_mensagens([payload.message_id])


@bot.event
async def on_raw_bulk_message_delete(payload):
    apagar_mensagens(payload.message_ids)


# ✅ numa mensagem que responde a um print: salva essa mensagem como a solução do print
@bot.event
async def on_raw_reaction_add(payload):
    if str(payload.emoji) != EMOJI_SOLUCAO or payload.guild_id is None or payload.user_id == bot.user.id:
        return

    msg = await buscar_mensagem(payload.channel_id, payload.message_id)
    if msg is None or msg.reference is None or msg.reference.message_id is None:
        return

    texto = msg.content.strip()
    if not texto or texto.startswith(bot.command_prefix) or not tem_print(msg.reference.message_id):
        return

    salvar_solucao(msg.reference.message_id, msg, texto, "reacao")
    try:
        await msg.add_reaction(EMOJI_SALVO)
    except discord.HTTPException:
        pass


# Tiraram o último ✅: a mensagem deixa de ser solução
@bot.event
async def on_raw_reaction_remove(payload):
    if str(payload.emoji) != EMOJI_SOLUCAO:
        return

    msg = await buscar_mensagem(payload.channel_id, payload.message_id)
    if msg is None or any(str(r.emoji) == EMOJI_SOLUCAO for r in msg.reactions):
        return

    cur.execute("DELETE FROM solucoes WHERE solucao_message_id = ? AND origem = 'reacao'", (str(msg.id),))
    if cur.rowcount:
        conn.commit()
        try:
            await msg.remove_reaction(EMOJI_SALVO, bot.user)
        except discord.HTTPException:
            pass


@bot.event
async def on_command_error(ctx, erro):
    if isinstance(erro, commands.CommandNotFound):
        return
    if isinstance(erro, commands.MissingPermissions):
        await ctx.send("🔒 Só administradores podem usar esse comando.")
        return
    if isinstance(erro, (commands.MissingRequiredArgument, commands.BadArgument, commands.BadUnionArgument)):
        await ctx.send(f"Uso: `!{ctx.command.qualified_name} {ctx.command.signature}`")
        return
    if isinstance(erro, commands.NoPrivateMessage):
        await ctx.send("Esse comando só funciona dentro do servidor.")
        return

    traceback.print_exception(type(erro), erro, erro.__traceback__)
    await ctx.send("❌ Deu erro ao executar o comando.")


# COMANDO BUSCAR ---------------------------------------------------------------------------------------------------------------------------------------
# Texto do print menor que a busca é comparado inteiro: senão um print com só "x" dá 100% em qualquer busca com "x"
def nota(termo, texto, score_cutoff=0, **_):
    if len(texto) < len(termo):
        return fuzz.ratio(termo, texto, score_cutoff=score_cutoff)
    return fuzz.partial_ratio(termo, texto, score_cutoff=score_cutoff)


# Ordena pela nota e, no empate, pelo print mais recente
def pontuar(termo_norm, linhas):
    textos = {i: linha[5] for i, linha in enumerate(linhas)}
    pontuados = process.extract(termo_norm, textos, scorer=nota, score_cutoff=NOTA_MINIMA, limit=None)
    return sorted(pontuados, key=lambda p: (-p[1], -int(linhas[p[2]][0])))


# Busca por várias frases e fica com a melhor nota de cada print; as outras frases que também bateram somam um bônus
# (mesmo erro e mesma rotina vale mais que só o mesmo erro), então a nota pode passar de 100: mostre com min(nota, 100).
# Retorna ([(posição, nota, frase que mais bateu)], se alguma frase identifica um erro de verdade).
# minimo: quantos prints precisam ter a frase (nota >= 90) para ela valer; 1 = a frase tem que existir no banco.
def pontuar_varias(consultas, linhas, excluir=(), minimo=0):
    por_consulta = [(consulta, pontuar(consulta, linhas)) for consulta in consultas]

    # Descarta as frases comuns demais; se todas forem, fica só com a mais rara
    def parecidos(resultados):
        return sum(1 for _, score, _ in resultados if score >= 90)

    limite = len(linhas) * FRASE_COMUM
    uteis = [p for p in por_consulta if minimo <= parecidos(p[1]) <= limite]
    especifico = bool(uteis)
    if not uteis and por_consulta and not minimo:
        uteis = [min(por_consulta, key=lambda p: parecidos(p[1]))]

    por_print = {}
    for consulta, resultados in uteis:
        for _, score, i in resultados:
            if linhas[i][0] not in excluir:
                por_print.setdefault(i, []).append((score, consulta))
    ordenados = []
    for i, notas in por_print.items():
        notas.sort(reverse=True)
        bonus = 0.1 * sum(score for score, _ in notas[1:])
        ordenados.append((i, notas[0][0] + bonus, notas[0][1]))
    ordenados.sort(key=lambda p: (-p[1], -int(linhas[p[0]][0])))
    return ordenados, especifico


# Um print inteiro tem muito ruído (menus, botões) que aparece em todas as telas do mesmo sistema.
# Então a busca usa só as frases que parecem ser o erro: com código de rejeição, senão com palavra de erro, senão as maiores.
PALAVRAS_ERRO = ("rejei", "erro", "obrigat", "inval", "nao permit", "falha", "inconsist", "diverg", "nao encontrad",
                 "negad", "duplic", "ja utiliz", "ja existe", "excede", "ausente", "bloquead")
FRASE_MAXIMA = 120  # frases longas deixam a busca lenta e o começo da mensagem já identifica o erro
FRASE_COMUM = 0.01  # frase que bate quase perfeito com mais de 1% dos prints é ruído (menu, título), não identifica o erro
CODIGO_REJEICAO = re.compile(r"\b\d{3}\s*[-–:.]?\s*rejei")
CODIGO_ERRO = re.compile(r"(?<![\d/.,])\d{3,4}\s*[-–]\s*[a-z]{3}")  # "225 - Falha no schema", sem a palavra "Rejeição"


def util(linha):
    return len(linha) >= 12 and sum(c.isalpha() for c in linha) >= len(linha) * 0.5


ERRO_DESC = re.compile(r"no\W*desc\W*")  # "Err No./Desc.: " depois de normalizar; o OCR às vezes lê "Em NoDesc"


# Janela "Ocorreu um Erro no Sistema": quase tudo nela é igual em todos os erros (12% dos prints). O que identifica o erro é
# a descrição ("Err No./Desc.: -2147217843 - Communication closed...", que quebra em várias linhas) e a rotina.
def frases_do_dialogo(linhas):
    frases, rotinas = [], []
    for i, linha in enumerate(linhas):
        norm = normalizar(linha)
        achou = ERRO_DESC.search(norm)
        if achou:
            partes = [re.sub(r"^-?\d+\W*", "", norm[achou.end():])]  # sem o número do erro: o OCR erra os dígitos
            for seguinte in linhas[i + 1:i + 4]:  # a descrição continua nas linhas de baixo
                seguinte = normalizar(seguinte)
                if len(seguinte.strip(" .")) < 4 or seguinte.startswith(("rotina", "anote")):  # linha solta do OCR ("S", "OK")
                    break
                partes.append(seguinte)
            frase = " ".join(" ".join(partes).split())
            if len(frase) >= 12:
                frases.append(frase[:FRASE_MAXIMA])
        elif re.match(r"\W*rotina\b", norm):
            frase = " ".join(re.sub(r"^\W*rotina\W*", "", norm).split())
            if len(frase) >= 12:
                rotinas.append(frase[:FRASE_MAXIMA])
    # "Rotina" também aparece fora da janela de erro: só vale com a descrição do erro ou o texto fixo da janela
    return frases + (rotinas if frases or e_janela_de_erro(linhas) else [])


# O texto fixo da janela "Ocorreu um Erro no Sistema"
def e_janela_de_erro(linhas):
    return any("anote os dados" in normalizar(l) or "ocorreu um" in normalizar(l) for l in linhas)


# Todas as linhas úteis do print, para quando as frases escolhidas pelas regras acima só deram texto genérico
def todas_as_frases(texto, maximo=10):
    linhas = [" ".join(l.split()) for l in texto.splitlines()]
    uteis = sorted({normalizar(l)[:FRASE_MAXIMA].strip() for l in linhas if util(l)}, key=len, reverse=True)
    return uteis[:maximo]


def frases_de_busca(texto, maximo=4):
    linhas = []
    for linha in texto.splitlines():
        linha = " ".join(linha.split())
        if linha:
            linhas.append(linha)
    dialogo = frases_do_dialogo(linhas)

    normais = [normalizar(l) for l in linhas]
    criterios = (
        lambda n: CODIGO_REJEICAO.search(n),
        lambda n: CODIGO_ERRO.search(n),
        lambda n: any(p in n for p in PALAVRAS_ERRO),
    )
    if dialogo:  # numa janela de erro, as linhas com a palavra "erro" são o texto fixo da janela: já sabemos que são genéricas
        criterios = criterios[:2]
    for criterio in criterios:
        indices = [i for i, n in enumerate(normais) if util(linhas[i]) and criterio(n)]
        if indices:
            break
    else:
        indices = [] if dialogo else sorted((i for i in range(len(linhas)) if util(linhas[i])), key=lambda i: -len(linhas[i]))

    frases = []
    for i in indices[:maximo]:
        frase = linhas[i]
        if len(frase) < 40 and i + 1 < len(linhas) and i + 1 not in indices:  # mensagem curta demais: provavelmente quebrou em duas linhas
            frase += " " + linhas[i + 1]
        frase = normalizar(frase)
        frase = frase.split("certificado")[0].strip() or frase  # o que vem depois é o nome do cliente, que muda de print para print
        codigo = CODIGO_REJEICAO.search(frase) or CODIGO_ERRO.search(frase)
        if codigo:  # começa no código: tira o "Deu Erro. Mensagem de retorno da Sefaz:" que vem antes e é igual em todo print
            frase = frase[codigo.start():]
        frases.append(frase[:FRASE_MAXIMA])
    return dialogo + [f for f in frases if f not in dialogo]


def imagens_da_mensagem(msg):
    return [a for a in msg.attachments if a.filename.lower().endswith(EXTENSOES)]


def textos_salvos(message_id):
    linhas = cur.execute("SELECT text_content FROM images WHERE message_id = ? AND text_norm != ''", (str(message_id),)).fetchall()
    return [l[0] for l in linhas]


# Texto dos prints de uma mensagem: do banco se já foi lido (o on_message lê antes do comando rodar), senão faz o OCR agora
async def textos_da_mensagem(msg):
    textos = textos_salvos(msg.id)
    if textos:
        return textos
    for arq in imagens_da_mensagem(msg):
        texto = await ocr_do_anexo(arq)
        if texto:
            textos.append(texto)
    return textos


# Texto do print que a pessoa mandou junto com o comando, ou do print da mensagem que ela respondeu. None = não tem print.
async def print_da_pergunta(ctx):
    if imagens_da_mensagem(ctx.message):
        return await textos_da_mensagem(ctx.message)

    ref = ctx.message.reference
    if ref is not None and ref.message_id is not None:
        textos = textos_salvos(ref.message_id)
        if textos:
            return textos
        origem = ref.resolved if isinstance(ref.resolved, discord.Message) else await buscar_mensagem(ref.channel_id, ref.message_id)
        if origem is not None and imagens_da_mensagem(origem):
            return await textos_da_mensagem(origem)
    return None


@bot.command()
async def buscar(ctx, *, termo=""):
    termo = termo.strip()
    consultas = [normalizar(limpar(termo))] if termo else []
    excluir = {str(ctx.message.id)}  # o print da própria pergunta não pode ser resposta dele mesmo
    de_print = False

    async with ctx.typing():
        textos = await print_da_pergunta(ctx)
        if textos is not None:
            de_print = True
            for texto in textos:
                consultas += [c for c in frases_de_busca(texto) if c not in consultas]
            if not consultas:
                await ctx.send("❌ Não consegui ler texto nesse print. Tente um print mais nítido ou escreva o erro: `!buscar <texto do erro>`.")
                return

        if not consultas:
            await ctx.send(
                "Escreva o erro (`!buscar 241 faixa já utilizado`) ou **mande o print junto com o comando** "
                "(ou responda a um print com `!buscar`)."
            )
            return

        linhas = cur.execute("""
            SELECT message_id, attachment_id, channel_id, guild_id, text_content, text_norm
            FROM images WHERE text_norm != ''
        """).fetchall()
        pontuados, especifico = await asyncio.to_thread(pontuar_varias, consultas, linhas, excluir)

        # Janela de erro em que só deu frase genérica (a linha "Err No./Desc." não foi lida): tenta com todas as linhas
        # do print, ficando com as raras que existem no banco. Só nas janelas: em outros prints isso casaria menus e botões.
        if de_print and not termo and not especifico and any(e_janela_de_erro(t.splitlines()) for t in textos):
            extras = [f for t in textos for f in todas_as_frases(t) if f not in consultas]
            outros, achou = await asyncio.to_thread(pontuar_varias, extras, linhas, excluir, 1) if extras else ([], False)
            if achou:
                consultas, pontuados, especifico = extras, outros, True

    if de_print and not termo and not especifico:
        await ctx.send(
            "🤔 Não consegui identificar a mensagem de erro nesse print: só achei textos que aparecem em todos os prints. "
            "Tente um print que mostre a mensagem de erro, ou escreva o erro: `!buscar <texto do erro>`."
        )
        return

    # Uma mensagem com vários prints aparece uma vez só, com a melhor nota
    resultados = []
    vistos = set()
    for i, score, consulta in pontuados:
        if linhas[i][0] in vistos:
            continue
        vistos.add(linhas[i][0])
        resultados.append((linhas[i], score, consulta))
        if len(resultados) == MAX_RESULTADOS:
            break

    if not resultados:
        await ctx.send("❌ Nenhum print encontrado. Tente escrever o texto do erro como aparece na tela.")
        return

    if de_print:
        embed = discord.Embed(title="🔎 Busca pelo print", color=0x2B88D8)
        embed.description = "Procurei por: " + " | ".join(f"`{c[:80]}`" for c in consultas[:3])
    else:
        embed = discord.Embed(title=f"🔎 {termo[:200]}", color=0x2B88D8)

    for (msg_id, _, canal_id, guild_id, texto, texto_norm), score, consulta in resultados:
        guild_id = guild_id or (ctx.guild.id if ctx.guild else "@me")
        link = f"https://discord.com/channels/{guild_id}/{canal_id}/{msg_id}"
        valor = f"[Abrir print]({link}) — `{data_da_mensagem(msg_id)}`\n> {recortar_trecho(texto, texto_norm, consulta)}"

        solucoes = cur.execute(
            "SELECT texto, channel_id, solucao_message_id FROM solucoes WHERE print_message_id = ? ORDER BY rowid DESC LIMIT 2",
            (msg_id,),
        ).fetchall()
        for sol_texto, sol_canal, sol_id in solucoes:
            sol_link = f"https://discord.com/channels/{guild_id}/{sol_canal}/{sol_id}"
            sol_texto = " ".join(sol_texto.split())
            if len(sol_texto) > 300:
                sol_texto = sol_texto[:300] + "…"
            valor += f"\n{EMOJI_SOLUCAO} **Solução:** {sol_texto} ([ver]({sol_link}))"

        embed.add_field(name=f"{min(score, 100):.0f}% de semelhança", value=valor[:1024], inline=False)

    await ctx.send(embed=embed)


# COMANDO SOLUÇÃO ---------------------------------------------------------------------------------------------------------------------------------------
@bot.command()
async def solucao(ctx, *, texto):
    ref = ctx.message.reference
    if ref is None or ref.message_id is None:
        await ctx.send("↩️ Use o `!solucao` **respondendo** à mensagem do print.")
        return

    if not tem_print(ref.message_id):
        await ctx.send("❌ A mensagem respondida não tem print indexado.")
        return

    salvar_solucao(ref.message_id, ctx.message, limpar(texto), "comando")
    await ctx.message.add_reaction(EMOJI_SALVO)


# CONTAS QUANTAS MSG TEM ------------------------------------------------------------------------------------------------------------------------------------
@bot.command()
@commands.has_permissions(administrator=True)
async def contarmensagens(ctx, canal: Union[discord.TextChannel, discord.Thread], limite: int = None):
    total = 0
    msg_status = await ctx.send(f"Contando... {canal.mention}...")

    try:
        async for _ in canal.history(limit=limite):
            total += 1
    except discord.HTTPException:
        await ctx.send("❌ Não foi possível acessar o histórico do canal.")
        return

    await msg_status.edit(content=f"O canal {canal.mention} tem **{total}** mensagens.")


# INDEXAR ---------------------------------------------------------------------------------------------------------------------------------------
async def rodar_indexacao(ctx, canais, limite, titulo):
    if indexacao_lock.locked():
        await ctx.send("⏳ Já tem uma indexação rodando, espere ela terminar.")
        return

    async with indexacao_lock:
        status = await ctx.send(f"🔄 {titulo}")
        progresso = Progresso(status, titulo)
        for canal in canais:
            await indexar_canal(canal, limite, progresso)
        await progresso.atualizar(forcar=True, fim=True)


@bot.command()
@commands.guild_only()
async def indexar(ctx, limite: int = None):
    canais = list(ctx.guild.text_channels) + list(ctx.guild.forums)
    alcance = "todas as mensagens" if limite is None else f"{limite} mensagens"
    await rodar_indexacao(ctx, canais, limite, f"Indexando {alcance} de cada canal...")


@bot.command()
@commands.guild_only()
async def indexarcanal(ctx, canal: Union[discord.TextChannel, discord.ForumChannel, discord.Thread], limite: int = None):
    alcance = "todas as mensagens" if limite is None else f"{limite} mensagens"
    await rodar_indexacao(ctx, [canal], limite, f"Indexando {alcance} de {canal.mention}...")


# REOCR ---------------------------------------------------------------------------------------------------------------------------------------
REOCR_PARALELO = int(os.environ.get("REOCR_PARALELO", "6"))  # prints lidos ao mesmo tempo (um processo do Tesseract cada)
REOCR_LOTE = 20


async def reocr_mensagem(message_id, canal_id, progresso, sem):
    async with sem:
        try:
            canal = bot.get_channel(int(canal_id)) or await bot.fetch_channel(int(canal_id))
            msg = await canal.fetch_message(int(message_id))
        except discord.NotFound:  # mensagem ou canal apagados
            apagar_mensagens([message_id])
            progresso.apagados += 1
            return
        except discord.HTTPException as err:
            print(f"Sem acesso à mensagem {message_id}:", err)
            mencao = f"<#{canal_id}>"
            if mencao not in progresso.erros:
                progresso.erros.append(mencao)
            return

        ids = {str(a.id) for a in msg.attachments if a.filename.lower().endswith(EXTENSOES)}
        if not ids:  # mensagem editada, sem o print
            cur.execute("DELETE FROM images WHERE message_id = ?", (str(message_id),))
            progresso.apagados += 1
            return

        progresso.novos += await indexar_mensagem(msg, refazer=True)
        marcas = ",".join("?" * len(ids))
        cur.execute(
            f"DELETE FROM images WHERE message_id = ? AND attachment_id != ? AND attachment_id NOT IN ({marcas})",
            (str(message_id), ANEXO_ANTIGO, *ids),
        )


@bot.command()
@commands.guild_only()
async def reocr(ctx, limite: int = None):
    if indexacao_lock.locked():
        await ctx.send("⏳ Já tem uma indexação rodando, espere ela terminar.")
        return

    async with indexacao_lock:
        sql = "SELECT DISTINCT message_id, channel_id FROM images WHERE ocr_versao < ? ORDER BY message_id DESC"
        pendentes = cur.execute(sql + (" LIMIT ?" if limite else ""), (OCR_VERSAO, limite) if limite else (OCR_VERSAO,)).fetchall()
        restantes = cur.execute("SELECT COUNT(DISTINCT message_id) FROM images WHERE ocr_versao < ?", (OCR_VERSAO,)).fetchone()[0]

        if not pendentes:
            await ctx.send("✅ Todos os prints já foram lidos com o OCR atual.")
            return

        titulo = f"Relendo {len(pendentes)} de {restantes} mensagens com o OCR novo (os mais recentes primeiro)..."
        progresso = Progresso(await ctx.send(f"🔄 {titulo}"), titulo, rotulo="Prints relidos")
        sem = asyncio.Semaphore(REOCR_PARALELO)

        for i in range(0, len(pendentes), REOCR_LOTE):
            lote = pendentes[i:i + REOCR_LOTE]
            await asyncio.gather(*(reocr_mensagem(m, c, progresso, sem) for m, c in lote))
            progresso.mensagens += len(lote)
            await progresso.atualizar()

        await progresso.atualizar(forcar=True, fim=True)


# BUSCA DE RELATÓRIOS ---------------------------------------------------------------------------------------------------------------------------------------
ICONE_TIPO = {"pdf": "📄", "exportacao": "📊"}
LIMITE_EMBED = 5500  # o Discord recusa embed com mais de 6000 caracteres


class BaixarArquivo(discord.ui.Select):
    """Menu com os arquivos da resposta: quem escolhe recebe o arquivo só para ele (não enche o canal)."""

    def __init__(self, arquivos):
        opcoes = [
            discord.SelectOption(label=rotulo[:100], value=str(arq.id), description=nome[:100], emoji=ICONE_TIPO[arq.tipo])
            for nome, arq, rotulo in arquivos[:25]
        ]
        super().__init__(placeholder="📎 Baixar um dos arquivos...", options=opcoes)

    async def callback(self, interaction):
        arq = catalogo.arquivo_por_id(int(self.values[0]))
        caminho = Path(arq.caminho) if arq else None
        if caminho is None or not caminho.exists():
            await interaction.response.send_message("❌ Não achei esse arquivo no computador do bot.", ephemeral=True)
            return
        await interaction.response.send_message(file=discord.File(caminho), ephemeral=True)


class VerNoMenu(discord.ui.Select):
    """Menu com as telas da resposta: quem escolhe recebe o print do menu do SPICA com a tela circulada, só para ele."""

    def __init__(self, telas):
        opcoes = [discord.SelectOption(label=t.nome[:100], value=f"{t.versao}|{t.codigo}", description=t.area[:100], emoji="📍")
                  for t in telas[:25]]
        super().__init__(placeholder="📍 Ver onde fica no menu...", options=opcoes)

    async def callback(self, interaction):
        versao, codigo = self.values[0].split("|", 1)
        png = await asyncio.to_thread(mapa_menus.desenhar, versao, codigo)
        if png is None:
            await interaction.response.send_message("❌ Ainda não tenho o print do menu dessa tela.", ephemeral=True)
            return
        await interaction.response.send_message(file=discord.File(io.BytesIO(png), "menu.png"), ephemeral=True)


class ArquivosView(discord.ui.View):
    def __init__(self, arquivos, telas=()):
        super().__init__(timeout=900)
        self.mensagem = None
        self.add_item(BaixarArquivo(arquivos))
        if telas:
            self.add_item(VerNoMenu(telas))

    async def on_timeout(self):
        for item in self.children:
            item.disabled = True
        if self.mensagem is not None:
            try:
                await self.mensagem.edit(view=self)
            except discord.HTTPException:
                pass


def embed_do_relatorio(consulta, busca):
    """Embed com as telas encontradas e o menu para baixar os arquivos. Retorna (embed, [(tela, arquivo, rótulo)], [telas])."""
    embed = discord.Embed(title=f"📑 {consulta[:200]}", color=0x2B88D8)
    filtro = {"pdf": " · só PDF", "exportacao": " · só exportações"}.get(busca.tipo, "")
    expressao = " ou ".join(" e ".join(f"`{termo}`" for termo in grupo) for grupo in busca.grupos)  # `venda` e `custo` / `ipi` ou `icms`
    embed.description = f"Telas que têm {expressao}\n**{busca.total_telas}** tela(s) · **{busca.total_layouts}** layout(s){filtro}"
    tamanho = len(embed.title) + len(embed.description)
    arquivos, telas, mostradas = [], [], 0

    for achado in busca.achados[:relatorios.MAX_ROTINAS]:
        rotina = achado.rotina
        titulo = f"{rotina.nome}{' †' if rotina.parcial else ''}"[:256]
        linhas = [f"*{rotina.area}* · {achado.casados} de {len(rotina.arquivos)} layout(s)"]
        rotulos = relatorios.rotulos_unicos([arq for arq, _, _ in achado.layouts])
        for (arq, _, trecho), rotulo in zip(achado.layouts, rotulos):
            linha = f"{ICONE_TIPO[arq.tipo]} **{rotulo[:120]}**"
            if trecho:
                linha += f"\n> {trecho}"
            linhas.append(linha)
        if achado.casados > len(achado.layouts):
            linhas.append(f"_+ {achado.casados - len(achado.layouts)} layout(s) com isso_")
        valor = "\n".join(linhas)[:1024]
        if tamanho + len(titulo) + len(valor) > LIMITE_EMBED:
            break
        tamanho += len(titulo) + len(valor)
        embed.add_field(name=titulo, value=valor, inline=False)
        arquivos += [(rotina.nome, arq, rotulo) for (arq, _, _), rotulo in zip(achado.layouts, rotulos)]
        telas.append(rotina)
        mostradas += 1

    rodape = f"† cobertura parcial: nem todos os layouts desta tela foram salvos · só a {busca.versao}"
    if busca.total_telas > mostradas:
        rodape = f"+{busca.total_telas - mostradas} tela(s): refine a busca · " + rodape
    embed.set_footer(text=rodape)
    return embed, arquivos, telas


@bot.command(aliases=["relatorios"])
async def relatorio(ctx, *, consulta=""):
    await ctx.send(
        "Agora o comando diz a versão do SPICA:\n"
        f"`!relatoriov8 {consulta.strip() or 'ipi'}` · `!relatoriov7 {consulta.strip() or 'ipi'}`"[:1900]
    )


@bot.command(aliases=["relatoriosv7"])
async def relatoriov7(ctx, *, consulta=""):
    await buscar_relatorio(ctx, consulta, "V7")


@bot.command(aliases=["relatoriosv8"])
async def relatoriov8(ctx, *, consulta=""):
    await buscar_relatorio(ctx, consulta, "V8")


async def buscar_relatorio(ctx, consulta, versao):
    consulta = consulta.strip()
    comando = f"!relatorio{versao.lower()}"
    if not catalogo.pronto:
        await ctx.send("O catálogo de relatórios ainda não foi montado. Use `!atualizarrelatorios`.")
        return

    async with ctx.typing():
        busca = await asyncio.to_thread(catalogo.buscar, consulta, versao) if consulta else None

    if busca is None or (not busca.termos and not busca.aviso):
        await ctx.send(
            "Qual informação você procura? Exemplos:\n"
            f"`{comando} ipi` · `{comando} ipi, icms` (um **ou** outro) · `{comando} ipi + icms` (os **dois**)\n"
            f"`{comando} pdf paciente` · `{comando} excel base de calculo` (filtre por PDF ou exportação)"
        )
        return
    if busca.aviso:
        await ctx.send(busca.aviso)
        return
    if not busca.achados:
        texto = f"❌ Não achei `{consulta[:100]}` em nenhum relatório ou exportação da {versao}."
        if busca.sugestao:
            texto += f"\nVocê quis dizer `{busca.sugestao}`?"
        await ctx.send(texto + "\n_Só acho o que aparece nos arquivos que foram salvos no levantamento._")
        return

    embed, arquivos, telas = embed_do_relatorio(consulta, busca)
    com_menu = [t for t in telas if mapa_menus.tem_posicao(t.versao, t.codigo)]
    view = ArquivosView(arquivos, com_menu)
    view.mensagem = await ctx.send(embed=embed, view=view)


@bot.command()
async def atualizarrelatorios(ctx):
    """Relê as pastas do levantamento e refaz o catálogo (use quando entrarem relatórios novos)."""
    if relatorios_lock.locked():
        await ctx.send("⏳ O catálogo já está sendo atualizado.")
        return
    try:
        from catalogo_relatorios import reconstruir
    except ImportError as erro:
        await ctx.send(f"❌ Faltam bibliotecas para ler os arquivos ({erro.name}). Rode `pip install -r requirements.txt`.")
        return

    async with relatorios_lock:
        status = await ctx.send("🔄 Lendo os relatórios da V7 e da V8 na pasta do levantamento (leva uns 20 segundos)...")
        try:
            telas, arquivos = await asyncio.to_thread(reconstruir)
        except Exception as erro:
            traceback.print_exception(type(erro), erro, erro.__traceback__)
            await status.edit(content="❌ Não consegui ler a pasta dos relatórios. Veja o terminal do bot.")
            return
        catalogo.carregar()
        mapa_menus.recarregar()
        await status.edit(content=f"✅ Catálogo atualizado: **{telas}** telas e **{arquivos}** arquivos.")


# AJUDA ---------------------------------------------------------------------------------------------------------------------------------------
@bot.command(name="ajuda", aliases=["help"])
async def ajuda(ctx):
    embed = discord.Embed(title="🤖 Bot de erros", color=0x2B88D8)
    embed.add_field(name="🔎 !buscar <texto do erro>", inline=False, value=(
        "Procura prints com esse texto.\n"
        "Quanto mais palavras do erro, melhor: `!buscar 241 Rejeição número da faixa já utilizado` "
        "acha melhor que `!buscar 241`. Acentos não importam."
    ))
    embed.add_field(name="📸 !buscar com o print", inline=False, value=(
        "Não sabe como escrever o erro? **Mande o print junto com o comando**: anexe a imagem e escreva `!buscar` na mensagem.\n"
        "Também funciona **respondendo** a um print com `!buscar`. O bot lê o print e procura erros parecidos."
    ))
    embed.add_field(name=f"{EMOJI_SOLUCAO} Registrar a solução", inline=False, value=(
        f"Responda ao print explicando como resolveu e reaja com {EMOJI_SOLUCAO} na resposta, "
        "ou responda ao print com `!solucao <como resolveu>`.\n"
        f"O bot confirma com {EMOJI_SALVO} e a solução passa a aparecer no `!buscar`."
    ))
    embed.add_field(name="📥 Indexação", inline=False, value=(
        "`!indexar [limite]` — lê os prints que faltam de todos os canais\n"
        "`!indexarcanal <#canal> [limite]` — lê os prints de um canal\n"
        "`!reocr [limite]` — relê com o OCR novo os prints que foram lidos com o antigo (pode parar e continuar depois)"
    ))
    embed.add_field(name="📑 !relatoriov8 / !relatoriov7 <informação>", inline=False, value=(
        "Descobre **qual relatório ou exportação do SPICA 8 (ou 7) tem** uma informação.\n"
        "`!relatoriov8 ipi, icms` — um **ou** outro · `!relatoriov7 ipi + icms` — os **dois**\n"
        "`!relatoriov8 pdf paciente` só PDFs · `!relatoriov7 excel base de calculo` só exportações\n"
        "Pelos menus da resposta você baixa o arquivo e vê, no print do menu do SPICA, onde a tela fica (circulada em vermelho)."
    ))
    embed.add_field(name="🔒 Administradores", inline=False, value=(
        "`!contarmensagens <#canal> [limite]` — conta as mensagens de um canal"
    ))
    await ctx.send(embed=embed)


# INICIA BOT ---------------------------------------------------------------------------------------------------------------------------------------
if __name__ == "__main__":
    if not TOKEN:
        raise SystemExit("Coloque o token no arquivo .env ao lado do bot_erros.py:  DISCORD_TOKEN=seu_token")
    if not Path(pytesseract.pytesseract.tesseract_cmd).exists():
        print(f"⚠️ Tesseract não encontrado em {pytesseract.pytesseract.tesseract_cmd} — os prints não serão lidos.")
    bot.run(TOKEN)
