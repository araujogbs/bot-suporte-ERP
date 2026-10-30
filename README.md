# bot-suporte-ERP — v2.0

Bot de Discord para o time de suporte de um ERP. Ele **lê os prints de erro** postados nos canais (OCR), guarda a
**solução** de cada erro e ajuda a **achar em qual relatório ou exportação está uma informação**, mostrando onde a tela
fica no menu. Hoje atende o **SPICA 7 e 8**.

A parte de erros (OCR, busca e soluções) não depende do sistema e serve para qualquer ERP. Só os comandos de relatório
(`!relatoriov7` e `!relatoriov8`, o catálogo e os prints de menu) são específicos do SPICA.

> Projeto de uso interno do suporte. O SPICA é um software da Joinner Sistemas; este projeto não é afiliado nem
> mantido por ela.

A primeira versão, mais simples, está na tag [`v1.0`](../../releases/tag/v1.0).

## Por que este bot existe

Foi uma **iniciativa de Gabriel Araújo**, do suporte, para tirar o conhecimento do time de dentro do histórico do chat.

### O gargalo

- **Os mesmos erros voltam, e as respostas ficavam enterradas no Discord.** Os prints de erro e as soluções ficavam
  espalhados em milhares de mensagens (o banco já passa de **13,5 mil prints**). Para achar um erro parecido era preciso
  lembrar quem resolveu ou rolar o histórico, e a solução, quando existia, era uma resposta perdida no meio da conversa.
- **Descobrir em qual relatório está um campo era manual.** O SPICA tem centenas de relatórios e exportações, cada um com
  vários layouts, nas versões 7 e 8. Responder "qual relatório mostra o IPI?" ou "onde fica essa tela no menu?" pedia abrir
  as telas uma a uma.

### Como o bot resolve

- **Memória compartilhada do suporte.** Todo print postado é lido e indexado. Quem recebe um erro cola o print (ou digita o
  texto) e o bot mostra os casos parecidos, com data, link da conversa original e a solução registrada.
- **A solução fica junto do erro.** Quem resolve responde ao print com `!solucao` (ou reage com ✅) e, daí em diante, todo
  mundo vê a solução ao buscar aquele erro.
- **Catálogo de relatórios pesquisável.** `!relatoriov7` e `!relatoriov8` dizem em quais telas, layouts e campos uma informação
  aparece (hoje são **459 telas e 1.337 arquivos** catalogados), com o arquivo para baixar e o código do layout.
- **A tela localizada no menu.** O bot envia o print do menu do SPICA com a tela circulada em vermelho, para quem está
  atendendo achar sem procurar.

### Como a equipe usa hoje

O bot roda no próprio Discord do suporte, então a **equipe toda** usa sem instalar nada:

1. Chegou um erro? Cola o print com `!buscar` e vê se já foi resolvido.
2. Resolveu algo novo? Responde ao print com `!solucao` (ou ✅). A base cresce sozinha com o uso.
3. Dúvida sobre relatório? `!relatoriov8 <campo>` ou `!relatoriov7 <campo>`, e o menu **📍 Ver onde fica no menu**.
4. Quem administra o bot usa `!indexar` e `!reocr` para ler o histórico e manter a base em dia.

## O que ele faz

### 1. Acha erros que já apareceram
- Lê com OCR todo print novo postado nos canais e guarda o texto (SQLite).
- `!buscar <texto>` procura prints com aquele erro. Acentos e maiúsculas não importam.
- `!buscar` com um **print anexado** (ou respondendo a um print) lê a imagem, usa só as frases do erro e procura os parecidos.
  Reconhece a janela "Ocorreu um Erro no Sistema" e os códigos de rejeição da Sefaz.
- Mostra os 5 mais parecidos, com data, link da mensagem original e a **solução registrada**.

### 2. Guarda a solução
- Responda ao print com `!solucao <como resolveu>`, ou responda explicando e reaja com ✅. O bot confirma com 💾.
- Tirar o ✅ desfaz.

### 3. Acha o relatório certo no SPICA 7 e 8
- `!relatoriov8 <informação>` e `!relatoriov7 <informação>` dizem em quais telas (relatórios e exportações) aparece um campo.
  - `ipi, icms` = um **ou** outro · `ipi + icms` = os **dois** · `pdf paciente` só PDFs · `excel base de calculo` só exportações.
  - Plural e singular valem igual e, se você errar a palavra, ele sugere ("você quis dizer…?").
- A resposta traz a tela (aba > grupo do menu), os layouts que batem, os campos em negrito e o código do layout impresso no
  PDF (por exemplo `V020_11`), que distingue layouts com o mesmo nome.
- O menu **📎 Baixar um dos arquivos** envia o arquivo só para quem escolher.
- O menu **📍 Ver onde fica no menu** envia o print do menu do SPICA com a tela **circulada em vermelho**.
- `!atualizarrelatorios` relê a pasta dos relatórios e refaz o catálogo.

### 4. Indexação do histórico
`!indexar`, `!indexarcanal` e `!reocr` leem o histórico dos canais, tópicos e fóruns. Pulam o que já foi lido e podem ser
interrompidos e retomados.

A lista completa de comandos está em [`docs/COMANDOS.txt`](docs/COMANDOS.txt) (e no `!ajuda`, dentro do Discord).

## Como é organizado

| Arquivo | Para que serve |
|---|---|
| `bot_erros.py` | O bot: OCR, banco de prints, `!buscar`, soluções, indexação e os comandos de relatório. |
| `relatorios.py` | Busca nos relatórios (OU/E, filtros, plural, "você quis dizer", trecho em negrito). |
| `catalogo_relatorios.py` | Monta o catálogo (`relatorios.db`) a partir da pasta com os PDFs e exportações do levantamento. |
| `mapa_menus.py` | Acha cada tela nos prints do menu (OCR) e desenha a elipse vermelha. |
| `menus/` | Os prints do menu (não vão para o GitHub; veja [`menus/LEIA-ME.md`](menus/LEIA-ME.md)). |
| `docs/` | Comandos e histórico de melhorias. |

## Instalação

Precisa de **Python 3.10+** e do **Tesseract** com o idioma português (`por`), no caminho padrão
`C:\Program Files\Tesseract-OCR\` (ou defina `TESSERACT_CMD`).

```bash
pip install -r requirements.txt
```

1. No [Discord Developer Portal](https://discord.com/developers/applications), crie o bot e ligue a intent **Message Content**.
2. Copie `.env.exemplo` para `.env` e coloque o token em `DISCORD_TOKEN`. O `.env` nunca vai para o Git.
3. Rode:

```bash
python bot_erros.py
```

Na primeira vez, se já existir um `prints.db` da versão 1, o bot converte o banco sozinho e guarda uma cópia
(`prints_backup_DATA.db`). Depois, rode `!indexar` uma vez para completar os prints antigos.

### Para os comandos de relatório (opcional)

1. Junte os PDFs e exportações do SPICA numa pasta (`V7`, `V7 TODOS`, `V8` e `V8 TODOS`) e aponte a variável de ambiente
   `RELATORIOS_DIR` para ela. A pasta `V7`/`V8` guarda só os que citam imposto; `V7 TODOS`/`V8 TODOS` guarda tudo.
2. Gere o catálogo: `python catalogo_relatorios.py` (ou `!atualizarrelatorios` no Discord). Também cria uma planilha de
   revisão por versão (`relatorios_v7_rotinas.xlsx`, `relatorios_v8_rotinas.xlsx`).
3. Para o "Ver onde fica no menu", monte a pasta `menus/` e rode `python mapa_menus.py`
   ([instruções](menus/LEIA-ME.md)).

## Privacidade

O `prints.db` guarda o **texto dos prints dos clientes**. Ele, o `.env` e os bancos de catálogo estão no `.gitignore` e
**não devem ser publicados**.

## O que mudou da v1 para a v2

Token fora do código, vários prints por mensagem, OCR fora do loop do bot, busca sem acento e por print, soluções,
indexação retomável, os comandos de relatórios do SPICA 7 e 8 e o menu com a tela circulada. O histórico completo está em
[`docs/MELHORIAS.md`](docs/MELHORIAS.md).
