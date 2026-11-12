# Evidências — screenshots reais do protótipo

Gerados por `scripts/capture.mjs` em Chromium headless, 1920×1080, perfil `high`
(exceto o nº 12), com o tempo congelado (`freeze=1`) para serem reprodutíveis.
A renderização foi **por software** (SwiftShader): as imagens são fiéis ao que o shader
produz, mas não dizem nada sobre desempenho em GPU real.

| Arquivo | Estado | Quadro de referência comparado |
|---|---|---|
| `01-repouso.jpg` | Repouso | `detalhes_monitor/tela_08s.jpg`, `tela_44s.jpg` |
| `02-escuta.jpg` | Escuta (ondas externas) | `detalhes_monitor/tela_08s.jpg` |
| `03-pensando.jpg` | Pensando | — (estado não aparece isolado na referência) |
| `04-falando.jpg` | Falando, voz baixa (onda) | `detalhes_monitor/tela_12s.jpg` |
| `05-falando-disposicao.jpg` | Falando, voz alta (estrela) + cartão de clima | `detalhes_monitor/tela_46s.jpg` |
| `06-rosto-lendo.jpg` | Rosto DEMO, em verificação | `detalhes_monitor/tela_04s.jpg` |
| `07-rosto-confirmado.jpg` | Rosto DEMO, confirmado | `frames/frame_003.jpg` |
| `08-mapa-entrada.jpg` | Mapa DEMO, descida com cartões | `detalhes_monitor/tela_22s.jpg` |
| `09-mapa-cidade.jpg` | Mapa DEMO, cidade oblíqua | `detalhes_monitor/tela_28s.jpg` |
| `10-mapa-briefing.jpg` | Mapa DEMO, narração completa | `detalhes_monitor/tela_36s.jpg` |
| `11-repouso-clima.jpg` | Repouso após o mapa | `detalhes_monitor/tela_44s.jpg` |
| `12-repouso-baixa-qualidade.jpg` | Repouso no perfil `low` (sem bloom) | — |

Os quadros da referência não estão no repositório (vídeo de terceiros, uso privado).
Para ver lado a lado: copie `reference/` do kit para `jarvis-hud/` e rode `npm run compare`.

## Diferenças observadas na comparação lado a lado

**Palco (8 s, 12 s, 44 s, 46 s)**
- Meu arco superior é mais grosso e mais claro; na referência é uma faixa mais fina com um
  segundo arco bem próximo.
- A treliça dos cantos é regular (vigas radiais + diagonais); a original é mais irregular.
- A base da referência é mais clara e "leitosa", com menos linhas; a minha é azul mais
  profundo com mais anéis e raios.
- O pedestal original é um domo liso; o meu é escalonado em três degraus com frisos.
- As luzes de cidade da referência são menores e mais densas; as minhas são um pouco maiores.
- A superfície iluminada à direita tem menos textura de nuvem que a original.
- O núcleo original parece mais escuro e com mais "peso" nos colchetes laterais.

**Rosto (4 s, 6 s)**
- A máscara facial está mais estreita que o escudo da referência e não tem a região dos ombros.
- O painel de webcam mostra uma silhueta desenhada (nenhuma câmera é acessada), não vídeo.
- A legenda de confirmação usa Orbitron; a original é uma sem serifa larga mais pesada.

**Mapa (22–36 s)**
- A cidade é de blocos procedurais; a referência é fotogrametria aérea real. É o estado
  com menor fidelidade.
- Na entrada não há o recorte circular de foto aérea no centro; há um anel ciano.
- A narração da referência ocupa mais largura e tem letra maior.

**Movimento** — conferido rodando a sequência demo (`?demo=1`) e amostrando 10 instantes:
todos os estados e as duas névoas de transição ocorreram, sem erros no console. Suavidade e
fps em GPU real não foram avaliados.
