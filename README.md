# bot-suporte-ERP

Bot de Discord para o time de suporte de um ERP. Ele **lê os prints de erro** postados nos canais (OCR), guarda a
**solução** de cada erro e deixa a equipe **buscar** o que já foi resolvido.

A primeira versão, mais simples, está na tag [`v1.0`](../../releases/tag/v1.0).

## O que ele faz

- Lê com OCR todo print novo postado nos canais e guarda o texto (SQLite).
- `!buscar <texto>` procura prints com aquele erro. Acentos e maiúsculas não importam.
- `!buscar` com um **print anexado** (ou respondendo a um print) lê a imagem e procura os erros parecidos.
- Mostra os 5 mais parecidos, com data, link da mensagem original e a **solução registrada**.
- `!solucao <como resolveu>` (ou reação ✅ na resposta) guarda a solução junto do print.
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

## Privacidade

O `prints.db` guarda o texto dos prints dos clientes. Ele e o `.env` estão no `.gitignore` e não devem ser publicados.
