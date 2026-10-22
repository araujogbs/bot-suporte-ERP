# Melhorias do bot_erros

Versão anterior: tag `v1.0`.

## Segurança
- [x] Token fora do código (arquivo `.env`, veja `.env.exemplo`)
- [x] Só `!contarmensagens` exige administrador (`!indexar`, `!indexarcanal` e `!reocr` são liberados; só uma indexação roda por vez)

## Bugs
- [x] Mensagem com vários prints só guardava o último (chave agora é mensagem + anexo)
- [x] OCR travava o bot inteiro durante a indexação (roda numa thread separada)
- [x] Print com quase nenhum texto (ex.: só "x") dava 100% em qualquer busca
- [x] `.webp` aceito no automático mas ignorado no `!indexar`
- [x] `!indexar` e o automático tratavam prints sem texto de jeitos diferentes
- [x] `except: pass` escondia erros: agora mostra no fim da indexação os canais sem acesso
- [x] Banco criado na pasta de onde o bot era aberto (agora sempre ao lado do `bot_erros.py`)
- [x] Prints de mensagens apagadas continuavam aparecendo na busca
- [x] Duas indexações ao mesmo tempo (agora bloqueia a segunda)

## Solução junto com o erro
- [x] `!solucao <texto>` respondendo ao print salva a solução
- [x] Reagir com ✅ numa resposta ao print salva aquela resposta como solução (tirar o ✅ desfaz)
- [x] `!buscar` mostra a solução registrada junto com o resultado

## Busca
- [x] Ignorar acentos ("destinatario" acha "destinatário")
- [x] Mostrar o trecho do texto encontrado no resultado
- [x] Data tirada do próprio id da mensagem (antes era 1 chamada à API por resultado)
- [x] Empate de nota: mais recente primeiro
- [x] Busca roda fora do loop do bot (~0,1 s nos 13,5 mil prints)
- [x] Resultado em embed
- [x] **Buscar pelo print**: `!buscar` com a imagem anexada, ou respondendo a um print. O bot usa só as frases do erro (código de rejeição, palavras de erro) e ignora menus e botões e o nome do cliente. Descarta sozinho as frases que batem com mais de 1% do banco (ex.: "Deu Erro. Mensagem de retorno da Sefaz"), e avisa se o print só tem texto genérico. Usa o texto já salvo quando o print está no banco, e nunca devolve o próprio print da pergunta.

- [x] **Janela "Ocorreu um Erro no Sistema"** (12,8% dos prints): o bot reconhece a linha `Err No./Desc.` (juntando a descrição que quebra em várias linhas) e a `Rotina`, em vez de cair nas frases fixas da janela. Buscas com janela de erro que achavam algo: 71% → 100%
- [x] Se a janela só deu texto genérico, procura entre todas as linhas as raras que existem no banco (só em janelas de erro, para não casar menus e botões)
- [x] Mesmo erro na mesma rotina soma um bônus na nota, então vem primeiro

## OCR
- [x] Ampliar 2x prints pequenos (testado em 108 imagens: média 94,7% → 96,5%, pior caso 68% → 84%)
- [x] Caminho do Tesseract e idioma configuráveis no `.env`
- ~~Escala de cinza / inverter tema escuro / `por+eng`~~: testado, não fez diferença, descartado

## Indexação
- [x] `!indexar` e `!indexarcanal` usam a mesma função
- [x] Pula prints já indexados (rodar de novo é rápido)
- [x] Corrige sozinho os registros antigos (completa o id do anexo e relê mensagens com vários prints)
- [x] Inclui tópicos (threads) e fóruns, abertos e arquivados
- [x] Commit a cada 5 s em vez de 1 por print
- [x] `!indexarcanal` aceita `#canal` além do id

## Organização
- [x] Migração automática do banco antigo (com backup `prints_backup_DATA.db` antes)
- [x] `requirements.txt` e `.env.exemplo`
- [x] `!ajuda` em português, docs atualizadas

## Ideias para depois
- [x] `!reocr [limite]`: relê os prints antigos com o OCR novo, os mais recentes primeiro. Cada print tem uma marca da versão do OCR, então dá para parar e continuar. Mensagens apagadas ou editadas sem o print saem do banco.
- [ ] `!semsolucao`: listar os erros mais buscados que ainda não têm solução registrada
- [ ] Registrar as buscas feitas, para saber quais erros mais aparecem
- [ ] Busca com SQLite FTS5 se o banco passar de ~100 mil prints
- [ ] Tratar mensagens editadas (anexo removido)
- [ ] Rodar o bot como serviço do Windows (iniciar sozinho com o PC)
