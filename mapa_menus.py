"""Mostra onde fica cada tela no menu do SPICA: o print do menu com a rotina circulada em vermelho.

Os prints ficam em menus/. O `python mapa_menus.py` lê cada print com OCR, acha o item de cada tela do catálogo
(relatorios.db) e grava a posição em menus/indice.json. O bot só abre o print e desenha a elipse (desenhar).
"""
import io
import json
import os
import re
import sqlite3
import unicodedata
from pathlib import Path

import numpy as np
import pytesseract
from PIL import Image, ImageDraw
from rapidfuzz import fuzz

pytesseract.pytesseract.tesseract_cmd = os.environ.get("TESSERACT_CMD", r"C:\Program Files\Tesseract-OCR\tesseract.exe")
PASTA = Path(__file__).resolve().parent
MENUS = PASTA / "menus"
INDICE = MENUS / "indice.json"
BANCO = PASTA / "relatorios.db"
ESCALA = 3           # o OCR lê melhor o texto pequeno do menu ampliado
NOTA_MINIMA = 78     # semelhança mínima entre o nome da tela e o texto lido no menu
LACUNA_COLUNA = 14   # espaço em branco (px) que separa uma coluna do menu da outra (entre palavras são ~5 px)

# V8: cada aba da janela Relatórios é um print; o grupo (cabeçalho em negrito) separa as colunas.
V8_IMAGENS = {
    "R.Básicos": "v8_basicos.jpg", "R.Estoque": "v8_estoque.jpg", "R.Gerenciais": "v8_gerenciais.jpg",
    "R.Gerenciais II": "v8_gerenciais2.jpg", "R.Financ.": "v8_financ.jpg", "R. Auxiliares": "v8_auxiliares.jpg",
}
# Telas cujo nome no catálogo é diferente do texto que aparece no menu: código -> texto do menu
ROTULO_MENU = {
    ("V8", "w900"): "Individuais", ("V8", "w910"): "Aniversários", ("V8", "w915"): "Remetente",
    ("V8", "w905"): "Clientes Selecionados", ("V8", "w920"): "Fornecedores", ("V8", "w925"): "Para o Correio", ("V8", "w930"): "Produto (Jato)",
    ("V7", "l910"): "Faturamento", ("V7", "l900"): "Cirurgias e Procedimentos", ("V7", "l920"): "Vendas por Produto",
    ("V8", "w480"): "Compras Mês a Mês",  # a exportação sai da mesma tela que o relatório (v480)
    ("V8", "ods-pos-estoque-almox"): "Posição do Estoque - Exportação", ("V8", "ods-pos-estoque-consig"): "Posição do Estoque - Exportação",
}
# V7: cada submenu aberto é um print; a chave é a área da tela no catálogo ("Estoques > Listagens > Em Falta").
# V7: em cada print o painel do submenu encosta no menu pai; lemos só o painel filho (x0, y0, x1, y1 no print).
V7_RECORTES = {
    "v7_est_posicao.jpg": (261, 15, 588, 251), "v7_est_compras.jpg": (261, 41, 574, 373), "v7_est_falta.jpg": (261, 67, 526, 171),
    "v7_est_aux.jpg": (261, 96, 603, 273), "v7_est_ativo.jpg": (261, 125, 515, 164),
    "v7_bas_produtos.jpg": (185, 21, 432, 331), "v7_bas_caixas.jpg": (185, 41, 364, 100), "v7_bas_outras.jpg": (185, 60, 459, 158),
    "v7_ger_cirurgias.jpg": (224, 24, 600, 325), "v7_ger_pedidos.jpg": (224, 41, 495, 199), "v7_ger_caixas.jpg": (224, 61, 472, 160),
    "v7_ger_avulsas.jpg": (224, 81, 504, 142), "v7_ger_consig.jpg": (224, 99, 522, 309), "v7_ger_vendas.jpg": (224, 138, 524, 352),
    "v7_ger_aux.jpg": (224, 158, 510, 394), "v7_ger_novos.jpg": (224, 177, 549, 412), "v7_ger_graficos.jpg": (224, 197, 447, 258),
    "v7_ger_export.jpg": (224, 198, 592, 680), "v7_ger_export2.jpg": (0, 166, 657, 205),  # o 2º print repete o 1º; só as linhas Z e 0 são novas
    "v7_ger_servicos.jpg": (224, 236, 532, 277), "v7_ger_materiais.jpg": (224, 256, 487, 278),
    "v7_ger_debito.jpg": (224, 275, 467, 297),
    "v7_basicas.jpg": (394, 42, 586, 130), "v7_ger_fat.jpg": (630, 168, 985, 805),
    "v7_fin_pagar.jpg": (692, 134, 956, 455), "v7_fin_receber.jpg": (708, 168, 984, 538),
}
_LB, _LG = "L.Operacionais > Básicas", "L.Operacionais > Gerenciais"
V7_IMAGENS = {
    "Estoques > Listagens > Posição do Estoque": ["v7_est_posicao.jpg"],
    "Estoques > Listagens > Compras / Entrada de Mercadorias": ["v7_est_compras.jpg"],
    "Estoques > Listagens > Em Falta": ["v7_est_falta.jpg"],
    "Estoques > Listagens > Auxiliares": ["v7_est_aux.jpg"],
    "Estoques > Listagens > Ativo Fixo": ["v7_est_ativo.jpg"],
    f"{_LB} > Tabela de Preços": ["v7_basicas.jpg"],
    f"{_LB} > Produtos": ["v7_bas_produtos.jpg"], f"{_LB} > Caixas": ["v7_bas_caixas.jpg"], f"{_LB} > Outras": ["v7_bas_outras.jpg"],
    f"{_LG} > Cirurgias": ["v7_ger_cirurgias.jpg"], f"{_LG} > Pedidos": ["v7_ger_pedidos.jpg"],
    f"{_LG} > Análises de Caixas": ["v7_ger_caixas.jpg"], f"{_LG} > Análises de Saídas Avulsas": ["v7_ger_avulsas.jpg"],
    f"{_LG} > Consignações": ["v7_ger_consig.jpg"], f"{_LG} > Faturamento": ["v7_ger_fat.jpg"], f"{_LG} > Vendas": ["v7_ger_vendas.jpg"],
    f"{_LG} > Auxiliares": ["v7_ger_aux.jpg"], f"{_LG} > Novos Relatórios e Análises": ["v7_ger_novos.jpg"],
    f"{_LG} > Gráficos": ["v7_ger_graficos.jpg"], f"{_LG} > Exportação": ["v7_ger_export.jpg", "v7_ger_export2.jpg"],
    f"{_LG} > Faturamento de Serviços": ["v7_ger_servicos.jpg"], f"{_LG} > Materiais Consignados": ["v7_ger_materiais.jpg"],
    f"{_LG} > Notas de Débito": ["v7_ger_debito.jpg"],
    "Financeiro > Contas a Pagar > Listagens": ["v7_fin_pagar.jpg"], "Financeiro > Contas a Receber > Listagens": ["v7_fin_receber.jpg"],
}


def normalizar(texto):
    sem_acento = "".join(c for c in unicodedata.normalize("NFKD", texto.lower()) if not unicodedata.combining(c))
    return " ".join(re.sub(r"[^a-z0-9]+", " ", sem_acento).split())


V8_RECORTE = (112, 112, 1342, 702)  # só o corpo da janela Relatórios: fora dele há o texto da tela de fundo e as abas


def _faixas(ocupado, lacuna):
    """Trechos [ini, fim) onde há tinta, juntando os que ficam a `lacuna` px ou menos um do outro."""
    faixas = []
    for posicao in (i for i, v in enumerate(ocupado) if v):
        if faixas and posicao - faixas[-1][1] <= lacuna:
            faixas[-1][1] = posicao + 1
        else:
            faixas.append([posicao, posicao + 1])
    return faixas


def segmentos(imagem, recorte=None):
    """Itens do menu do print: [(texto_normalizado, (x0, y0, x1, y1), texto_preto)], na escala original.
    Acha as colunas e, em cada uma, as linhas de texto pelo espaço em branco; lê cada linha sozinha com o OCR.
    `recorte` limita a leitura a uma área do print."""
    dx, dy = recorte[:2] if recorte else (0, 0)
    if recorte:
        imagem = imagem.crop(recorte)
    rgb = imagem.convert("RGB")
    tinta = np.asarray(rgb).min(axis=2) < 170  # texto preto, cinza ou laranja; fundo branco/cinza claro fica de fora
    azul = rgb.split()[2]  # texto laranja tem pouco azul: fica escuro, como o preto
    itens = []
    for cx0, cx1 in _faixas(tinta.any(axis=0), LACUNA_COLUNA):
        for ly0, ly1 in _faixas(tinta[:, cx0:cx1].any(axis=1), 2):
            if ly1 - ly0 < 6:
                continue
            xs = np.flatnonzero(tinta[ly0:ly1, cx0:cx1].any(axis=0))
            x0, x1 = cx0 + int(xs[0]), cx0 + int(xs[-1]) + 1
            if x1 - x0 < 10:
                continue
            linha = azul.crop((x0 - 3, ly0 - 3, x1 + 3, ly1 + 3))
            linha = linha.resize((linha.width * ESCALA, linha.height * ESCALA), Image.LANCZOS)
            texto = normalizar(pytesseract.image_to_string(linha, lang="por", config="--psm 7"))
            if texto:
                caixa = (x0, ly0, x1, ly1)
                itens.append((texto, (x0 + dx, ly0 + dy, x1 + dx, ly1 + dy), _tinta_preta(rgb, caixa)))
    return itens


def _tinta_preta(rgb, caixa):
    """True se o texto da caixa é preto (cabeçalho de grupo no menu da V8); os itens são laranja."""
    pretos = laranjas = 0
    for r, g, b in rgb.crop(caixa).getdata():
        if r < 120 and g < 120 and b < 120:
            pretos += 1
        elif r > 200 and b < 130 and g < 200:
            laranjas += 1
    return pretos > laranjas


def _sem_prefixo(texto):
    """V7: o item do menu começa com a letra de atalho ('a faturamento por vendedor')."""
    return re.sub(r"^[a-z0-9] ", "", texto)


def largura_por_caractere(itens, v7):
    """Largura média (px) de cada caractere do menu, para estimar a largura que um nome deveria ter."""
    larguras = [(c[2] - c[0]) / len(_sem_prefixo(t) if v7 else t) for t, c, preto in itens if not preto and len(t) >= 12]
    return sorted(larguras)[len(larguras) // 2] if larguras else None


def _finalistas(candidatos):
    """Candidatos (nota, caixa) com nota perto da melhor: o OCR erra os numerais romanos ('II' vira nada ou '1'),
    então 'Exportação' e 'Exportação II' têm notas quase iguais e a largura da linha é que as distingue."""
    melhor = max(n for n, _ in candidatos)
    return [c for c in candidatos if c[0] >= melhor - 4]


def _desvio_largura(nome, caixa, k):
    return abs((caixa[2] - caixa[0]) - k * len(nome)) if k else 0


def _melhor(nome, candidatos, v7, k=None):
    alvo = normalizar(nome)
    achados = [(fuzz.ratio(alvo, _sem_prefixo(t) if v7 else t), c) for t, c, *_ in candidatos]
    achados = [a for a in achados if a[0] >= NOTA_MINIMA]
    if not achados:
        return None
    # o submenu mais fundo (mais à direita), depois a largura que combina com o nome, depois a nota
    return max(_finalistas(achados), key=lambda a: (a[1][0], -_desvio_largura(nome, a[1], k), a[0], -a[1][1]))


ROMANOS = {"i": 1, "ii": 2, "iii": 3, "iv": 4, "v": 5, "vi": 6, "vii": 7, "viii": 8, "ix": 9, "x": 10}


def base_e_numeral(nome):
    """('exportacao de notas fiscais modelo', 3) para 'Exportação de Notas Fiscais - Modelo III'; sem numeral vale 1."""
    palavras = normalizar(nome).split()
    if len(palavras) > 1 and palavras[-1] in ROMANOS:
        return " ".join(palavras[:-1]), ROMANOS[palavras[-1]]
    return " ".join(palavras), 1


def _linhas_da_base(base, arquivos, cache, v7):
    """Linhas dos prints que parecem o nome sem o numeral, de cima para baixo: [(arquivo, y, nota, caixa)].
    O OCR perde ou erra o numeral romano ('II' some, 'III' vira '1'), mas o menu lista as variantes em ordem."""
    achadas = []
    for ordem, arquivo in enumerate(arquivos):
        if arquivo not in cache:
            continue
        for texto, caixa, preto in cache[arquivo][0]:
            nota = fuzz.ratio(base, _sem_prefixo(texto) if v7 else texto)
            if (v7 or not preto) and nota >= 85:  # na V7 todo o texto é preto; na V8 preto é cabeçalho de grupo
                achadas.append((ordem, caixa[1], nota, caixa, arquivo))
    return sorted(achadas)


def posicao_v8(nome, grupo, itens, k=None):
    """Item laranja com o nome da tela. Se o mesmo nome aparece em mais de um grupo, vale o item cujo cabeçalho
    (texto preto acima dele, na mesma coluna) mais se parece com o grupo."""
    alvo, alvo_grupo = normalizar(nome), normalizar(grupo)
    candidatos = [(fuzz.ratio(alvo, t), c) for t, c, preto in itens if not preto and fuzz.ratio(alvo, t) >= NOTA_MINIMA]
    if not candidatos:
        return None
    cabecalhos = [(t, c) for t, c, preto in itens if preto]

    def grupo_do(candidato):
        caixa = candidato[1]
        acima = [(t, c) for t, c in cabecalhos if abs(c[0] - caixa[0]) <= 30 and c[3] <= caixa[1] + 2]
        texto = max(acima, key=lambda h: h[1][3])[0] if acima else ""
        return fuzz.partial_ratio(alvo_grupo, texto)

    melhor_grupo = max(grupo_do(c) for c in candidatos)
    do_grupo = [c for c in candidatos if grupo_do(c) >= melhor_grupo - 10]  # o cabeçalho também sai do OCR com erros
    return max(_finalistas(do_grupo), key=lambda c: (-_desvio_largura(nome, c[1], k), c[0], -c[1][1]))


def construir():
    """Lê os prints e grava menus/indice.json. Retorna (achadas, sem_posicao)."""
    con = sqlite3.connect(BANCO)
    telas = con.execute("SELECT versao, codigo, nome, area FROM rotinas").fetchall()
    con.close()
    cache, indice, faltou = {}, {}, []
    telas = [(v, c, ROTULO_MENU.get((v, c), n), a) for v, c, n, a in telas]
    variantes = {}  # telas da mesma área que só se diferenciam pelo numeral romano: (versao, area, base) -> numerais
    for versao, codigo, nome, area in telas:
        base, numeral = base_e_numeral(nome)
        variantes.setdefault((versao, area, base), []).append(numeral)
    for versao, codigo, nome, area in telas:
        if versao == "V8":
            aba, _, grupo = area.partition(" > ")
            arquivos = [V8_IMAGENS[aba]] if aba in V8_IMAGENS else []
        else:
            arquivos, grupo = V7_IMAGENS.get(area, []), area.rpartition(" > ")[2]
        arquivos = [a for a in arquivos if (MENUS / a).exists()]
        for arquivo in arquivos:
            if arquivo not in cache:
                itens = segmentos(Image.open(MENUS / arquivo), V8_RECORTE if versao == "V8" else V7_RECORTES.get(arquivo))
                cache[arquivo] = (itens, largura_por_caractere(itens, versao == "V7"))
        melhor = None
        base, numeral = base_e_numeral(nome)
        irmas = sorted(variantes[(versao, area, base)])
        if len(irmas) > 1 and len(set(irmas)) == len(irmas):
            linhas = _linhas_da_base(base, arquivos, cache, versao == "V7")
            if len(linhas) == len(irmas):  # uma linha do menu para cada variante: a ordem do menu é a ordem dos numerais
                _, _, nota, caixa, arquivo = linhas[irmas.index(numeral)]
                melhor = ((nota, caixa), arquivo)
        for arquivo in arquivos if melhor is None else []:
            itens, k = cache[arquivo]
            achou = posicao_v8(nome, grupo, itens, k) if versao == "V8" else _melhor(nome, itens, True, k)
            if achou and (melhor is None or achou[0] > melhor[0][0]):
                melhor = (achou, arquivo)
        if melhor is None:
            faltou.append((versao, codigo, nome, area))
        else:
            (nota, caixa), arquivo = melhor
            indice[f"{versao}|{codigo}"] = {"imagem": arquivo, "caixa": list(caixa), "nota": nota}
    INDICE.write_text(json.dumps(indice, ensure_ascii=False, indent=1), encoding="utf8")
    return len(indice), faltou


def tem_posicao(versao, codigo):
    return f"{versao}|{codigo}" in _indice()


_cache_indice = {}


def _indice():
    if not _cache_indice and INDICE.exists():
        _cache_indice.update(json.loads(INDICE.read_text(encoding="utf8")))
    return _cache_indice


def recarregar():
    _cache_indice.clear()


def desenhar(versao, codigo):
    """PNG (bytes) do menu com a tela circulada em vermelho, ou None se não temos o print dela."""
    achou = _indice().get(f"{versao}|{codigo}")
    if not achou or not (MENUS / achou["imagem"]).exists():
        return None
    imagem = Image.open(MENUS / achou["imagem"]).convert("RGB")
    x0, y0, x1, y1 = achou["caixa"]
    folga_x, folga_y = 12, 7
    ImageDraw.Draw(imagem).ellipse((x0 - folga_x, y0 - folga_y, x1 + folga_x, y1 + folga_y), outline=(230, 0, 0), width=4)
    saida = io.BytesIO()
    imagem.save(saida, "PNG")
    return saida.getvalue()


if __name__ == "__main__":
    achadas, faltou = construir()
    print(f"{achadas} telas com posição no menu; {len(faltou)} sem:")
    for versao, codigo, nome, area in faltou:
        print(f"  {versao} {codigo} | {nome} | {area}")
