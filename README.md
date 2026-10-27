# bot-suporte-ERP

Bot de Discord para o time de suporte de um ERP. Ele **lê os prints de erro** postados nos canais (OCR), guarda a
**solução** de cada erro e ajuda a **achar em qual relatório ou exportação está uma informação**. Hoje atende o SPICA 7 e 8.

A primeira versão, mais simples, está na tag [`v1.0`](../../releases/tag/v1.0).

## O que ele faz

- Lê com OCR todo print novo postado nos canais e guarda o texto (SQLite).
- `!buscar <texto>` procura prints com aquele erro. Acentos e maiúsculas não importam.
- `!buscar` com um **print anexado** (ou respondendo a um print) lê a imagem e procura os erros parecidos.
- Mostra os 5 mais parecidos, com data, link da mensagem original e a **solução registrada**.
- `!solucao <como resolveu>` (ou reação ✅ na resposta) guarda a solução junto do print.
- `!relatoriov8 <informação>` e `!relatoriov7 <informação>` dizem em quais telas (relatórios e exportações) aparece um campo.
  `ipi, icms` = um **ou** outro · `ipi + icms` = os **dois** · `pdf paciente` só PDFs · `excel base de calculo` só exportações.
  A resposta traz a tela (aba > grupo do menu), os layouts, os campos em negrito e o menu **📎 Baixar um dos arquivos**.
- `!atualizarrelatorios` relê a pasta dos relatórios e refaz o catálogo (`catalogo_relatorios.py`).
- `!indexar`, `!indexarcanal` e `!reocr` leem o histórico dos canais, tópicos e fóruns, e podem ser retomados.

A lista de comandos está em [`docs/COMANDOS.txt`](docs/COMANDOS.txt) e no `!ajuda`.

## Instalação

Precisa de **Python 3.10+** e do **Tesseract** com o idioma português (`por`), em `C:\Program Files\Tesseract-OCR\`
(ou defina `TESSERACT_CMD`).

```bash
pip install -r requirements.txt
```

1. No Discord Developer Portal, crie o bot e ligue a intent **Message Content**.
2. Copie `.env.exemplo` para `.env` e coloque o token em `DISCORD_TOKEN`. O `.env` nunca vai para o Git.
3. `python bot_erros.py`

Na primeira vez, se já existir um `prints.db` da versão 1, o bot converte o banco e guarda uma cópia. Depois, rode `!indexar`.

### Para os comandos de relatório (opcional)

1. Junte os PDFs e exportações do SPICA numa pasta (`V7`, `V7 TODOS`, `V8` e `V8 TODOS`) e aponte a variável de ambiente
   `RELATORIOS_DIR` para ela.
2. Gere o catálogo: `python catalogo_relatorios.py` (ou `!atualizarrelatorios` no Discord).

## Privacidade

O `prints.db` guarda o texto dos prints dos clientes. Ele e o `.env` estão no `.gitignore` e não devem ser publicados.
