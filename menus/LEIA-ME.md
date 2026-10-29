# Prints do menu do SPICA

Esta pasta guarda os prints do menu do SPICA que o bot usa para mostrar, no `!relatoriov7` e no `!relatoriov8`, onde a
tela fica (circulada em vermelho). Os prints **não vão para o GitHub** (são a interface do SPICA); cada instalação tira os
seus.

## Como montar

1. **V8**: abra *Relatórios* e tire um print de cada aba da janela (R.Básicos, R.Estoque, R.Gerenciais, R.Gerenciais II,
   R.Financ. e R. Auxiliares). Os nomes esperados estão em `V8_IMAGENS`, no `mapa_menus.py`
   (`v8_basicos.jpg`, `v8_estoque.jpg`…).
2. **V7**: o menu é em cascata. Abra cada submenu, tire um print dele e salve com o nome que está em `V7_IMAGENS`
   (`v7_est_posicao.jpg`…). O recorte do painel de cada print fica em `V7_RECORTES` (coordenadas em pixels do print).
3. Rode, depois de gerar o catálogo (`python catalogo_relatorios.py`):

```bash
python mapa_menus.py
```

Ele lê os prints com OCR, acha o item de cada tela do catálogo e grava `menus/indice.json`. As telas que ele não achar
são listadas no final.

Se o menu do SPICA mudar, refaça os prints e rode de novo.
