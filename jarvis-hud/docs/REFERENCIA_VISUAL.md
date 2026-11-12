# Referência visual — interface holográfica JARVIS

Especificação extraída da inspeção dos quadros do kit `reference/` (24 frames de 2 em 2 s,
12 recortes ampliados do monitor e a folha de contato). O vídeo original (`1000199153.mp4`)
**não** estava disponível; nada aqui vem de quadros intermediários.

> O material é a gravação de um monitor curvo feita com celular e republicada como Reel.
> Tudo o que é moldura do monitor, webcam física, mesa, teclado, barra de tarefas do Windows
> e interface do Instagram (coração, contadores, legenda do post) foi **descartado**.
> Só a interface exibida no monitor é especificada.

## 1. Arquivos analisados

| Tempo | Arquivo | O que mostra (somente o que está no monitor) |
|---|---|---|
| 00 s | `frames/frame_000.jpg` | Borrão de movimento; já se vê a base circular azul embaixo e um painel à direita. |
| 02 s | `frames/frame_001.jpg`, `detalhes_monitor/tela_02s.jpg` | Verificação facial começando: painel de webcam à esquerda, busto de partículas ao centro, legenda sobre a base. |
| 04 s | `frames/frame_002.jpg`, `detalhes_monitor/tela_04s.jpg` | Busto em malha de pontos e linhas ciano; legenda **"Lendo seu rosto"**; painel direito com **"28 %"** e lista (ROSTO / PROVA DE VIDA / IDENTIDADE) e botão; painel inferior direito **"EM ESPERA"**. |
| 06 s | `frames/frame_003.jpg` | Tudo do estado facial fica **verde-água**: **"IDENTIDADE CONFIRMADA"**, subtítulo pequeno de boas-vindas, porcentagem **"100"**, webcam com tinta verde. Núcleo reduzido no topo, ao centro. Arco superior e estrutura dos cantos bem visíveis. |
| 08 s | `frames/frame_004.jpg`, `detalhes_monitor/tela_08s.jpg` | Núcleo grande em repouso: disco azul com **linha horizontal fina**, anel com **marcadores quadrados rosados**, e um **círculo fino bem maior** ao redor (onda se expandindo). Relógio digital **11:57:35** no painel inferior esquerdo. Luzes de cidade à esquerda. |
| 10 s | `frames/frame_005.jpg`, `detalhes_monitor/tela_10s.jpg` | Glifo central vira **estrela de 4 pontas**; marcadores rosados somem; legenda começa (**"Bom dia, …"**); painel direito **"JARVIS FALANDO"**. |
| 12 s | `frames/frame_006.jpg`, `detalhes_monitor/tela_12s.jpg` | Glifo vira **forma de onda horizontal** com lóbulos; legenda **"Bom dia, senhor. Vou dar uma olhada em …"** com o nome da cidade em ciano na 2ª linha. Colchetes escuros grossos à esquerda/direita do anel. |
| 14 s | `frames/frame_007.jpg` | Transição: câmera virtual mergulha em direção ao planeta (limbo azul nítido, luzes de cidade). |
| 16 s | `frames/frame_008.jpg` | O celular filma **outro monitor** (player de música). Fora do escopo. |
| 18–20 s | `frames/frame_009.jpg`, `frame_010.jpg` | Mapa visto de muito alto, **lavado de azul**; núcleo reduzido no topo; abas pequenas no canto superior direito. |
| 22 s | `frames/frame_011.jpg`, `detalhes_monitor/tela_22s.jpg` | Dois cartões de borda ciano luminosa: **clima** à esquerda ("Quase sem nuvens", sensação/umidade, máx/mín/vento) e **notícias** à direita (3 manchetes com rodapé). Ao centro, um recorte circular de imagem aérea crescendo. |
| 24–38 s | `frames/frame_012…019.jpg`, `detalhes_monitor/tela_24s/28s/32s/36s.jpg` | **Cidade 3D** em vista oblíqua: malha de ruas, telhados cerâmicos, coberturas claras, quadras arborizadas, um conjunto maior ao centro, avenida diagonal escura (28 s). **Anel ciano fino** sobre o terreno. Texto narrado sobreposto, centralizado, que vai sendo revelado palavra a palavra, com nomes e números em ciano. Fundo distante azulado. |
| 40 s | `frames/frame_020.jpg` | Mapa voltando a ficar azul/alto; núcleo reduzido com marcadores rosados. |
| 42 s | `frames/frame_021.jpg` | Retorno ao espaço: núcleo crescendo no canto, planeta com mancha urbana brilhante. |
| 44 s | `frames/frame_022.jpg`, `detalhes_monitor/tela_44s.jpg` | Palco holográfico de volta, repouso (linha + marcadores rosados). **Cartão de clima permanece** à esquerda, inclinado. |
| 46 s | `frames/frame_023.jpg`, `detalhes_monitor/tela_46s.jpg` | Fala final: **estrela/onda com pico vertical**; legenda **"Estou à sua disposição, senhor"**; abas "… CINEMA · … CINEMA · … AUTOMÁTIC…" legíveis no topo direito; arco duplo. |
| — | `contato_geral.jpg` | Visão geral usada para conferir a ordem e a duração de cada bloco. |

Textos pequenos (rótulos dos painéis, rodapés) estão ilegíveis na gravação; onde o protótipo
usa um rótulo nesses lugares, ele é **invenção minha** e está indicado na seção 9.

## 2. Composição do palco holográfico (8 s, 12 s, 44 s, 46 s)

Medidas em fração da tela do monitor (estimadas sobre os recortes; a gravação tem perspectiva
e a tela é curva, então há ±3 % de incerteza).

| Elemento | Posição / tamanho |
|---|---|
| Núcleo de anéis | centro em x 50 %, y ≈ 31–33 %; diâmetro externo (com colchetes) ≈ 48–52 % da altura |
| Feixe | do topo do pedestal até a base do núcleo; ≈ 18–20 % da altura; mais largo embaixo, cintura no meio |
| Pedestal | centro em y ≈ 84–86 %; largura ≈ 28 % da tela; elipse com razão ≈ 0,25 (visto ~14° de cima) |
| Base circular | ocupa toda a largura; borda distante em y ≈ 71–74 %; a parte próxima sai pela borda inferior |
| Arco superior | topo em y ≈ 8–10 %; encontra as laterais em y ≈ 50–55 %; segundo arco fino por dentro (46 s) |
| Legenda | centralizada, y ≈ 64–72 %, sobre o feixe |
| Painel inferior esquerdo (relógio) | ≈ 20–25 % da largura, inclinado para dentro |
| Painel inferior direito (estado) | simétrico ao relógio |
| Abas superiores direitas | 3 pares rótulo/valor em y ≈ 6–7 % |
| Cartão de clima (44–46 s) | borda esquerda, y ≈ 28–45 %, ≈ 22–25 % da largura, girado em Y |

**Fundo:** planeta em órbita baixa. Lado noturno à esquerda com **pontos brancos de cidades**
agrupados (x 0–30 %, y 20–55 %); **faixa de atmosfera azul** no limbo, da região superior
central descendo para a direita; superfície **azul-acinzentada com nuvens** à direita.

**Camadas, de trás para frente:** espaço/estrelas → planeta → atmosfera → estrutura dos cantos
e arco → base circular → pedestal → feixe → núcleo → partículas → HUD (painéis, legenda).

## 3. Núcleo (o elemento mais importante)

De fora para dentro, conforme `tela_08s`, `tela_12s`, `tela_44s`, `tela_46s`:

1. **Abas brancas** curtas às 3 h e 9 h, fora de tudo.
2. **Colchetes** grossos e escuros com borda acesa, à esquerda e à direita (~60° cada);
   segmentos do mesmo tipo no quadrante superior direito.
3. Anel fino claro completo.
4. **Régua** de marcas radiais curtas (bem visível na metade inferior aos 46 s).
5. **12 marcadores quadrados rosados** distribuídos no anel médio — presentes em repouso
   (8 s, 44 s) e no núcleo reduzido (40 s); ausentes enquanto fala (10 s, 12 s, 46 s).
6. Arcos segmentados médios.
7. **Anel interno grosso**, o mais claro do conjunto.
8. **Disco interno** de "vidro" azul, mais claro no centro.
9. **Glifo central:** linha horizontal (repouso) → onda com lóbulos (voz baixa, 12 s) →
   estrela com pico vertical (voz alta, 10 s e 46 s).

O corpo do anel é opaco/azul — não se vê o planeta através dele. Aos 44 s o conjunto aparece
com leve giro em Y, lido como **volume** (camadas em profundidades diferentes).

## 4. Paleta

Médias de regiões dos JPEGs (monitor filmado: valores lavados e com dominante azul; servem de
ordem de grandeza, não de cor exata).

| Uso | Amostra na referência | Usado no protótipo |
|---|---|---|
| Preenchimento da base | `#0E77D3` (12 s) | gradiente `#1E8AFF → #0840EB → #041C99` |
| Borda clara da base | `#1394E2` | linhas `#8CD9FF` + bloom |
| Disco interno do núcleo | `#074598` | `#0D4DFF → #03125C` |
| Arco superior | `#175DBE` (46 s) | `#298CFF → #0838E6`, filete interno quase branco |
| Feixe | `#3D89E6` | `#388CFF → #B3E6FF` aditivo |
| Céu noturno | `#1F2A4C` (com reflexo da sala) | `#010206` |
| Superfície iluminada | `#23375E` | `#05134A → #5778CC` |
| Marcadores | `#B26482` | `#FF6B9E` (antes do bloom) |
| Cartão: fundo / borda | `#1E2F5D` / `#085BAA` | `rgba(8,40,120,.78)` / `#49C2FF` |
| Destaque de legenda | `#319CCA` | `#55DCFF` |
| Confirmação (verde-água) | `#209B93` | `#5DFFC0` |
| Névoa do mapa | `#565C80`, distante `#355294` | `#335CD1` |
| Telhados | laranja-avermelhado (lavado nas amostras) | `#C2553A` e 5 variações |

Contraste: fundo quase preto, elementos azuis saturados, e apenas **três** acentos fora do azul —
branco quente (luzes de cidade), rosa (marcadores) e verde-água (confirmação).

## 5. Luz e pós-processamento

- Tudo que é linha clara **estoura** (halo): bloom forte com limiar alto.
- A base e o emissor iluminam a parte de baixo do feixe.
- Vinheta leve; grão/linhas de varredura muito sutis.
- Não há sombras nem materiais realistas: é luz emissiva + transparência aditiva.

## 6. Movimento

| Elemento | Comportamento observado |
|---|---|
| Anéis | giram em velocidades e sentidos diferentes (posições dos marcadores mudam entre 8 s e 44 s) |
| Onda externa | círculo fino maior que o núcleo aos 8 s — pulso que se expande |
| Glifo | reage à voz: linha → onda → estrela |
| Legendas | reveladas palavra a palavra (≈ 2,5–3 palavras/s entre 10–12 s e 24–36 s) |
| Câmera | mergulho em direção ao planeta (14 s) → vista alta azulada (18–22 s) → órbita oblíqua lenta sobre a cidade (24–38 s) → subida e retorno (40–44 s) |
| Núcleo | encolhe e sobe para o topo durante rosto e mapa |
| Rosto | porcentagem sobe (28 → 100), itens da lista acendem, tudo muda para verde |

## 7. Estados

| Estado | Evidência | Sinais visuais |
|---|---|---|
| Repouso | 8 s, 44 s | linha no glifo, marcadores rosados, "EM ESPERA" |
| Escuta | 8 s (círculo externo) | ondas se expandindo; glifo com vibração leve |
| Pensando | **não aparece isolado** na referência | definido por mim: anéis aceleram, marcadores acendem em sequência, arcos orbitando no glifo |
| Falando | 10–12 s, 46 s | onda/estrela, sem marcadores, "JARVIS FALANDO", legenda |
| Rosto | 2–6 s | máscara facial de pontos e linhas, webcam, porcentagem; verde ao confirmar |
| Mapa 3D | 18–40 s | cartões, cidade oblíqua, anel ciano, narração sobreposta |

## 8. Tipografia

- Rótulos e títulos de HUD ("JARVIS FALANDO", "IDENTIDADE CONFIRMADA", relógio): sem serifa
  **larga, geométrica, em maiúsculas com espaçamento aberto**. Protótipo: Orbitron (OFL).
- Legendas e textos dos cartões: sem serifa neutra tipo Arial/Helvetica, branco-azulado com
  brilho, espaço entre palavras generoso. Protótipo: Arial / Segoe UI do sistema.

## 9. O que é invenção do protótipo (não está legível ou não existe na referência)

- Rótulos pequenos: "HORA LOCAL", "ESTADO DO ASSISTENTE", "CORRESPONDÊNCIA", "CÂMERA".
- Rótulos "LUZ / RITMO / CÂMERA" das abas (só os valores "CINEMA" e "AUTOMÁTIC…" são legíveis).
- Estado **Pensando** inteiro e o texto "Ouvindo…".
- Conteúdo dos cartões e da narração (cidade, clima, manchetes): **fictício**, marcado `DEMO`.
- Selo "PROTÓTIPO VISUAL · DADOS SIMULADOS DEMO" e a barra de controles inferior.
- Detalhe fino da treliça dos cantos (na referência só se distinguem vigas escuras com
  filetes ciano).

## 10. Checklist de fidelidade

Comparação feita sobre `evidence/*.jpg` contra os recortes acima (ver `evidence/README.md`).

| Item | Situação |
|---|---|
| Núcleo de anéis no terço superior, com colchetes, régua, anel claro e disco de vidro | ✅ |
| Marcadores rosados em repouso, ausentes na fala | ✅ |
| Glifo linha → onda → estrela | ✅ |
| Onda externa na escuta | ✅ |
| Base circular larga em perspectiva rasante + pedestal + feixe | ✅ |
| Arco superior duplo com estrutura nos cantos | ✅ (treliça mais regular que a original) |
| Planeta: luzes à esquerda, faixa de atmosfera, lado iluminado à direita | ✅ |
| Painéis inclinados (relógio / estado), abas superiores | ✅ |
| Legenda centralizada com destaque ciano, revelada por palavra | ✅ |
| Cartão de clima inclinado à esquerda após o mapa | ✅ |
| Rosto: webcam à esquerda, máscara facial central, painel de % à direita, virada para verde | ✅ (máscara frontal com relevo; mais estreita que o escudo da referência, sem os ombros) |
| Mapa: entrada alta e azulada com dois cartões | ✅ (sem o recorte circular de foto aérea) |
| Mapa: cidade oblíqua com telhados cerâmicos, anel ciano e narração | ⚠️ parcial — blocos procedurais, não fotogrametria |
| Pedestal em domo liso | ⚠️ o meu é escalonado e mais contrastado |
| Base mais clara e "leitosa" | ⚠️ a minha é mais escura e com mais linhas |
