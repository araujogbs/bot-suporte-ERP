"""Busca nos relatórios e exportações do SPICA, a partir do banco que o catalogo_relatorios.py gera.

Consulta:  termos separados por vírgula (ou "ou") valem como OU; termos ligados por "+" valem como E.
Filtros:   pdf | excel (exportação) | v8 | v7, em qualquer lugar da consulta.
"""
import re
import sqlite3
import unicodedata
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from rapidfuzz import process
from rapidfuzz.distance import DamerauLevenshtein

BANCO = Path(__file__).resolve().parent / "relatorios.db"
MAX_ROTINAS = 6      # telas mostradas na resposta
MAX_LAYOUTS = 2      # layouts mostrados por tela
PESO_NOME, PESO_CABECALHO, PESO_TEXTO = 4, 2, 1  # achar no nome da tela vale mais que achar nas colunas
# False: procura só no título e nas colunas (os campos). True: procura também nos valores do relatório, que no teste
# são nomes de clientes, produtos e datas, e trazem tela que só "tem" a palavra num dado, não como campo.
BUSCAR_NO_CONTEUDO = False
FILTROS_PDF = {"pdf"}
FILTROS_EXPORTACAO = {"excel", "ods", "planilha"}
PREPOSICOES = {"de", "da", "do", "das", "dos", "para", "por", "em", "e", "p", "com", "sem", "x"}


def normalizar(texto):
    """Minúsculo, sem acento, pontuação vira espaço. Mantém o tamanho do texto, então a posição serve no original."""
    saida = []
    for ch in texto:
        base = unicodedata.normalize("NFKD", ch.lower())[0]
        saida.append(base if base.isalnum() else " ")
    return "".join(saida)


@dataclass
class Arquivo:
    id: int
    nome_arquivo: str
    tipo: str            # "pdf" ou "exportacao"
    caminho: str
    cita_imposto: bool
    titulo: str
    colunas: str         # nomes das colunas (exportação) ou o cabeçalho do relatório (PDF); sem o título
    texto: str           # o resto do arquivo, também sem o título
    nome_n: str = ""
    cab_n: str = ""
    texto_n: str = ""
    id_layout: str = ""  # código do layout impresso no rodapé do PDF ("V020_11"); a V7 e as exportações não têm


@dataclass
class Rotina:
    codigo: str
    versao: str
    nome: str
    area: str
    parcial: bool
    cita_imposto: bool
    arquivos: list = field(default_factory=list)


@dataclass
class Achado:
    rotina: Rotina
    layouts: list         # [(Arquivo, nota, trecho)] os melhores
    casados: int          # quantos layouts da tela bateram
    nota: float


@dataclass
class Busca:
    achados: list
    total_telas: int
    total_layouts: int
    termos: list
    tipo: str = None
    versao: str = None
    sugestao: str = None
    aviso: str = None
    grupos: list = field(default_factory=list)  # alternativas (OU); cada uma com os termos que precisam estar todos (E)


MESES = "janeiro|fevereiro|mar[çc]o|abril|maio|junho|julho|agosto|setembro|outubro|novembro|dezembro"
PERIODO = re.compile(
    rf"""\s*[-–]?\s*(?:
        \d{{2}}/\d{{2}}/\d{{4}}(?:\s+(?:e|a|até)\s+\d{{2}}/\d{{2}}/\d{{4}})?       # 01/01/2026 e 31/12/2026
      | (?:{MESES})/\d{{4}}(?:\s+(?:e|a|até)\s+(?:{MESES})/\d{{4}})?               # Janeiro/2026 a Dezembro/2026
      | \b20\d\d\b                                                                  # 2026
    )""",
    re.I | re.X,
)


def limpar_titulo(titulo):
    """Tira do título o período em que o relatório foi gerado: as datas só dependem do dia em que foi exportado."""
    limpo = PERIODO.sub("", titulo or "")
    limpo = re.sub(r"\s*[-–]\s*[-–]\s*", " - ", limpo)
    return " ".join(limpo.split()).strip(" -–")


ID_DO_PDF = re.compile(r"\(?([A-Za-z]\d{3}_\d+)\)")


def id_do_pdf(texto):
    """Código do layout que o SPICA imprime no rodapé de cada página do PDF, como '(V020_11)'. Vale o mais repetido."""
    achados = Counter(m.upper() for m in ID_DO_PDF.findall(texto))
    return achados.most_common(1)[0][0] if achados else ""


def rotulo(arq):
    """Nome do layout para mostrar, com o código do layout na frente quando o PDF traz. Exportação que começa direto
    pelas colunas não tem título: usa as colunas."""
    titulo = limpar_titulo(arq.titulo)
    if not titulo:
        colunas = [c.strip() for c in arq.colunas.split(" | ") if c.strip()]
        if arq.tipo == "exportacao" and colunas:
            return f"Layout sem título ({len(colunas)} colunas)"
        numero = re.search(r"_(\d+)\.pdf$", arq.nome_arquivo, re.I)  # os PDFs vêm numerados pelo layout
        titulo = f"Layout {numero.group(1)}" if numero else arq.nome_arquivo
    return f"{arq.id_layout} · {titulo}" if arq.id_layout else titulo


def _num_colunas(arq):
    return arq.colunas.count(" | ") + 1 if arq.tipo == "exportacao" and arq.colunas else 0


def rotulos_unicos(arquivos):
    """Rótulos dos layouts mostrados juntos. Se ficariam iguais, distingue pelo número de colunas (exportações)
    ou, não dando, por um número de ordem."""
    nomes = [rotulo(a) for a in arquivos]
    saida = list(nomes)
    for nome in set(nomes):
        grupo = [i for i, n in enumerate(nomes) if n == nome]
        if len(grupo) < 2:
            continue
        colunas = [_num_colunas(arquivos[i]) for i in grupo]
        layouts = [re.search(r"_(\d+)\.pdf$", arquivos[i].nome_arquivo, re.I) for i in grupo]
        if all(colunas) and len(set(colunas)) == len(grupo):
            for i, n in zip(grupo, colunas):
                saida[i] = f"{nome} · {n} colunas"
        elif all(layouts) and len({m.group(1) for m in layouts}) == len(grupo):  # PDF: o número do layout vem no nome do arquivo
            for i, m in zip(grupo, layouts):
                saida[i] = f"{nome} · layout {int(m.group(1))}"
        else:
            for ordem, i in enumerate(grupo, 1):
                saida[i] = f"{nome} ({ordem})"
    return saida


def interpretar(consulta):
    """Separa filtros e termos. Retorna (grupos, tipo, versao): cada grupo é uma lista de termos que precisam estar todos."""
    tipo = versao = None
    grupos = []
    for parte in re.split(r"[,;]|\bou\b", consulta, flags=re.I):
        palavras = parte.split()
        restantes = []
        for i, palavra in enumerate(palavras):
            baixa = normalizar(palavra).strip()
            proxima = normalizar(palavras[i + 1]).strip() if i + 1 < len(palavras) else ""
            if baixa in FILTROS_PDF:
                tipo = "pdf"
            elif baixa in FILTROS_EXPORTACAO:
                tipo = "exportacao"
            elif baixa == "exportacao" and i == 0 and proxima and proxima not in PREPOSICOES:
                tipo = "exportacao"  # "exportacao icms" = só exportações com ICMS; "exportacao de notas" = nome de tela
            elif baixa in ("v7", "v8"):
                versao = baixa.upper()
            else:
                restantes.append(palavra)
        termos = [" ".join(normalizar(t).split()) for t in " ".join(restantes).split("+")]
        termos = [t for t in termos if len(t) >= 2 and any(p not in PALAVRAS_VAZIAS for p in t.split())]  # "de" sozinho não é busca
        if termos:
            grupos.append(termos)
    return grupos, tipo, versao


# o que o cabeçalho do PDF tem além dos nomes dos campos: empresa, página, datas e valores
RUIDO_PDF = re.compile(r"Joinner Sistemas|Pag\.?\s*:|Data\s*:|\d{2}/\d{2}/\d{4}|www\.joinner\.com\.br|\b\d{1,3}(?:\.\d{3})*,\d{2}\b")

TROCAS_DE_PLURAL =(("al", "ais"), ("el", "eis"), ("ol", "ois"), ("ul", "uis"), ("il", "is"), ("ao", "oes"), ("ao", "aes"), ("ao", "aos"), ("m", "ns"))


def _variantes(palavra):
    """A palavra e o seu singular/plural: fiscal<->fiscais, lancamento<->lancamentos, exportacao<->exportacoes."""
    variantes = {palavra}
    if len(palavra) > 3 and palavra.endswith("s"):
        variantes.add(palavra[:-1])
    for singular, plural in TROCAS_DE_PLURAL:
        if len(palavra) > len(singular) + 2 and palavra.endswith(singular):
            variantes.add(palavra[:-len(singular)] + plural)
        if len(palavra) > len(plural) + 2 and palavra.endswith(plural):
            variantes.add(palavra[:-len(plural)] + singular)
    return sorted(variantes, key=len, reverse=True)


def _regex(termo):
    # começa em fronteira de palavra ("ipi" não casa dentro de "recipiente"), mas aceita o que vem depois ("impostos")
    palavras = ["(?:" + "|".join(re.escape(v) for v in _variantes(p)) + ")" for p in termo.split()]
    return re.compile(r"(?<![a-z0-9])" + r"\s+".join(palavras))


PALAVRAS_VAZIAS = PREPOSICOES | {"o", "a", "os", "as", "no", "na", "nos", "nas", "um", "uma"}


def _padroes(termo):
    """A frase inteira e, separadas, as palavras que importam (sem 'de', 'da', 'com'...)."""
    palavras = [p for p in dict.fromkeys(termo.split()) if p not in PALAVRAS_VAZIAS]
    return _regex(termo), [_regex(p) for p in palavras]


def _onde(rx, arq):
    """(peso, lugar) do melhor lugar do arquivo onde o padrão aparece, ou None."""
    if rx.search(arq.nome_n):
        return PESO_NOME, "nome"
    if rx.search(arq.cab_n):
        return PESO_CABECALHO, "cabecalho"
    if BUSCAR_NO_CONTEUDO and rx.search(arq.texto_n):
        return PESO_TEXTO, "texto"
    return None


def _fim_da_palavra(norm, fim):
    while fim < len(norm) and norm[fim].isalnum():  # "impost" -> "imposto"
        fim += 1
    return fim


def _limpo(texto):
    return " ".join(texto.replace("*", "").replace("`", "'").split())


def _celula_em_negrito(celula, achou):
    """O nome da coluna com a palavra achada em negrito."""
    ini, fim = achou.start(), _fim_da_palavra(normalizar(celula), achou.end())
    return f"{_limpo(celula[:ini])} **{_limpo(celula[ini:fim])}** {_limpo(celula[fim:])}".strip()


def _janelas_em_negrito(texto, norm, achados, antes=2, depois=2, junta=25):
    """PDF: cada palavra achada, em negrito, com duas palavras de cada lado (sem empresa, página, datas e valores).
    Palavras da busca que estão perto uma da outra viram uma janela só."""
    texto = texto.replace("*", " ").replace("`", "'")  # mesmo tamanho: as posições do normalizado continuam valendo
    achados = sorted((a.start(), _fim_da_palavra(norm, a.end())) for a in achados)
    grupos = []
    for ini, fim in achados:
        if grupos and ini - grupos[-1][-1][1] <= junta:
            grupos[-1].append((ini, fim))
        else:
            grupos.append([(ini, fim)])
    janelas = []
    for grupo in grupos:
        ini, fim = grupo[0][0], grupo[-1][1]
        miolo, pos = [], ini
        for p_ini, p_fim in grupo:
            miolo += [texto[pos:p_ini], "**", texto[p_ini:p_fim], "**"]
            pos = p_fim
        miolo.append(texto[pos:fim])
        ant = RUIDO_PDF.sub(" ", texto[:ini]).split()[-antes:]
        dep = RUIDO_PDF.sub(" ", texto[fim:]).split()[:depois]
        janelas.append(" ".join((" ".join(ant) + " " + "".join(miolo) + " " + " ".join(dep)).split()))
    return janelas


class Catalogo:
    def __init__(self, banco=BANCO):
        self.banco = Path(banco)
        self.rotinas = {}
        self.arquivos = []
        self.vocabulario = []
        self.carregar()

    @property
    def pronto(self):
        return bool(self.arquivos)

    def carregar(self):
        self.rotinas, self.arquivos, self.vocabulario = {}, [], []
        if not self.banco.exists():
            return
        con = sqlite3.connect(self.banco)
        for codigo, versao, nome, area, parcial, imposto in con.execute("SELECT codigo, versao, nome, area, parcial, cita_imposto FROM rotinas"):
            self.rotinas[(versao, codigo)] = Rotina(codigo, versao, nome, area, bool(parcial), bool(imposto))
        palavras = Counter()
        for id_, codigo, versao, nome_arq, tipo, caminho, imposto, titulo, colunas, texto in con.execute(
                "SELECT id, codigo, versao, nome_arquivo, tipo, caminho, cita_imposto, titulo, colunas, texto FROM arquivos"):
            rotina = self.rotinas.get((versao, codigo))
            if rotina is None:
                continue
            arq = Arquivo(id_, nome_arq, tipo, caminho, bool(imposto), titulo or "", colunas or "", texto or "")
            arq.nome_n = normalizar(f"{rotina.nome} {rotina.area} {limpar_titulo(arq.titulo)}")
            arq.cab_n = normalizar(arq.colunas)
            arq.texto_n = normalizar(arq.texto)
            if tipo == "pdf":
                arq.id_layout = id_do_pdf(arq.texto)
            rotina.arquivos.append(arq)
            self.arquivos.append((rotina, arq))
            palavras.update(w for w in (arq.nome_n + " " + arq.cab_n).split() if len(w) >= 4 and not w.isdigit())
        con.close()
        self.vocabulario = [w for w, n in palavras.items() if n >= 1]

    @property
    def versoes(self):
        return sorted({r.versao for r in self.rotinas.values()})

    def arquivo_por_id(self, id_):
        return next((a for _, a in self.arquivos if a.id == id_), None)

    def buscar(self, consulta, versao=None):
        """versao: "V7" ou "V8" (o comando usado); sem ela vale o v7/v8 escrito na consulta, ou as duas."""
        grupos, tipo, versao_escrita = interpretar(consulta)
        versao = versao or versao_escrita
        termos = [t for g in grupos for t in g]
        busca = Busca([], 0, 0, termos, tipo, versao, grupos=grupos)
        if versao and versao not in self.versoes:
            busca.aviso = f"O catálogo ainda não tem a **{versao}**: use `!atualizarrelatorios` depois de salvar os arquivos dela."
            return busca
        if not grupos:
            return busca

        padroes = {t: _padroes(t) for t in termos}
        por_rotina = {}
        for rotina, arq in self.arquivos:
            if (tipo and arq.tipo != tipo) or (versao and rotina.versao != versao):
                continue
            nota, onde = self._nota(arq, grupos, padroes)
            if nota:
                por_rotina.setdefault((rotina.versao, rotina.codigo), []).append((arq, nota, onde))

        achados = []
        for chave, casados in por_rotina.items():
            casados.sort(key=lambda c: -c[1])
            rotina = self.rotinas[chave]
            layouts = [(a, n, self._campos(a, o)) for a, n, o in casados[:MAX_LAYOUTS]]
            achados.append(Achado(rotina, layouts, len(casados), casados[0][1] + 0.01 * min(len(casados), 20)))
        achados.sort(key=lambda a: (-a.nota, -a.casados, a.rotina.nome, a.rotina.versao))
        busca.achados = achados
        busca.total_telas = len(achados)
        busca.total_layouts = sum(a.casados for a in achados)
        if not achados:
            busca.sugestao = self._sugerir(grupos)
        return busca

    @staticmethod
    def _nota(arq, grupos, padroes):
        """Nota do arquivo: soma, entre os grupos (OU) que ele satisfaz (E), de onde cada termo apareceu.
        A frase inteira vale mais; se ela não aparece, vale ter todas as palavras dela no arquivo (pelo pior lugar)."""
        total, onde = 0, {}
        for grupo in grupos:
            parcial, achou = 0, {}
            for termo in grupo:
                frase, palavras = padroes[termo]
                lugar = _onde(frase, arq)
                if lugar:
                    peso, nome_lugar = lugar
                    peso, rx = peso + 0.5, frase
                elif len(palavras) > 1 and all(_onde(p, arq) for p in palavras):
                    peso, nome_lugar = min(_onde(p, arq) for p in palavras)
                    rx = next(p for p in palavras if _onde(p, arq)[1] == nome_lugar)
                else:
                    parcial = 0
                    break
                parcial += peso
                achou[termo] = (nome_lugar, rx)
            if parcial:
                total += parcial
                onde.update(achou)
        return total, onde

    @staticmethod
    def _campos(arq, onde, limite=170):
        """Só os campos (colunas) do layout que têm o que foi buscado, em negrito e separados por ·, de cada palavra da
        busca. Vazio quando só o título bateu: o título já aparece como nome do layout."""
        pedacos, achados_pdf = [], []
        for _, rx in onde.values():
            if arq.tipo == "exportacao":
                encontradas = 0
                for celula in arq.colunas.split(" | "):
                    achou = rx.search(normalizar(celula))
                    if achou and encontradas < 3:
                        pedacos.append(_celula_em_negrito(celula, achou))
                        encontradas += 1
            else:
                achou = rx.search(arq.cab_n)
                if achou:
                    achados_pdf.append(achou)
        if achados_pdf:
            pedacos += _janelas_em_negrito(arq.colunas, arq.cab_n, achados_pdf)
        texto = ""
        for pedaco in dict.fromkeys(p for p in pedacos if p):
            novo = f"{texto} · {pedaco}" if texto else pedaco
            if texto and len(novo) > limite:
                return texto + " · …"
            texto = novo
        return texto

    def _sugerir(self, grupos):
        """'Você quis dizer': troca palavras que não existem em nenhum arquivo pela mais parecida que existe."""
        if not self.vocabulario:
            return None
        existentes = set(self.vocabulario)
        trocou = False
        novos = []
        for grupo in grupos:
            termos = []
            for termo in grupo:
                palavras = []
                for p in termo.split():
                    if len(p) >= 4 and not any(v.startswith(p) for v in existentes):
                        # Damerau conta letras trocadas de lugar como 1 erro só ("icsm" -> "icms")
                        melhor = process.extractOne(p, self.vocabulario, scorer=DamerauLevenshtein.normalized_similarity, score_cutoff=0.7)
                        if melhor:
                            p, trocou = melhor[0], True
                    palavras.append(p)
                termos.append(" ".join(palavras))
            novos.append(" + ".join(termos))
        return ", ".join(novos) if trocou else None
