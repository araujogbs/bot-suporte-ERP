# spica-bot-suporte — v1.0

Bot de Discord para o time de suporte. Ele **lê com OCR os prints de erro** que o pessoal posta nos canais,
guarda o texto num banco local e permite **buscar um erro** que já apareceu antes.

> Esta é a primeira versão, feita à mão. A versão 2.0 está na branch `main`.

## Como funciona

1. Cada print novo (`png`, `jpg`, `jpeg`, `bmp`, `webp`) postado num canal é lido com o Tesseract.
2. O texto lido vai para um banco SQLite (`prints.db`), junto com o id da mensagem, do canal e do autor.
3. O `!buscar` compara o que você digitou com o texto de todos os prints e devolve os 5 mais parecidos, com o link da
   mensagem original e a data.

## Comandos

| Comando | O que faz |
|---|---|
| `!buscar <texto do erro>` | Mostra até 5 prints parecidos (nota, link e data). Quanto mais palavras do erro, melhor. |
| `!indexar [limite]` | Lê os prints antigos de todos os canais de texto. Sem número, lê tudo. |
| `!indexarcanal <id do canal> [limite]` | O mesmo, só para um canal. |
| `!contarmensagens <id do canal> [limite]` | Conta quantas mensagens o canal tem. |

## Instalação

Precisa de **Python 3.10+** e do **Tesseract** com o idioma português (`por`), instalado em
`C:\Program Files\Tesseract-OCR\` (ou ajuste o caminho no começo do `bot_erros.py`).

```bash
pip install -r requirements.txt
```

No Discord Developer Portal, ligue as intents **Message Content** e **Server Members** do bot.

O token vai na última linha do `bot_erros.py` (`bot.run("")`). **Nunca publique o arquivo com o token preenchido.**

```bash
python bot_erros.py
```

## Limitações desta versão

- Mensagem com vários prints guarda só o último.
- O OCR roda no mesmo processo do bot e trava tudo durante a indexação.
- O token fica no código.
- A busca compara com todos os prints a cada comando e não ignora acentos.

Tudo isso foi resolvido na versão 2.0.
