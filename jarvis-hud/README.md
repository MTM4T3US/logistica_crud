# JARVIS HUD — protótipo visual (DEMO)

Recriação, com recursos gráficos originais, da interface holográfica mostrada no monitor do
vídeo de referência: núcleo de anéis azul, base circular com pedestal e feixe, arco superior,
planeta com luzes de cidades, painéis laterais, legendas e mapa 3D.

**É só a camada visual.** Não há voz, microfone, câmera, reconhecimento facial, clima, notícias
nem mapas reais — tudo isso é simulado e aparece marcado como `DEMO` na tela. Nenhum hardware
é acionado.

Esta pasta é independente do CRUD de logística que está na raiz do repositório.

## Rodar no Windows

1. Instale o [Node.js LTS](https://nodejs.org) (20 ou mais novo).
2. No PowerShell, dentro desta pasta:

   ```powershell
   cd jarvis-hud
   npm install
   npm run dev
   ```

3. Abra <http://127.0.0.1:5173> no Chrome ou Edge e aperte `F` para tela cheia.

Atalho: com o Node.js instalado, dê dois cliques em `INICIAR.bat`. Ele faz o `npm install`
na primeira vez e abre o navegador. (Escrito sem acesso a uma máquina Windows — se falhar,
use os comandos acima.)

Para a versão otimizada: `npm run build` e depois `npm run preview` (porta 4173).

Se o Windows estiver usando a GPU integrada, force a dedicada em
*Configurações → Sistema → Tela → Elementos gráficos* para o navegador.

## Controles

| Tecla | Ação |
|---|---|
| `1` Repouso · `2` Escuta · `3` Pensando · `4` Falando | estados do assistente |
| `5` Rosto · `6` Mapa 3D | demonstrações (dados simulados) |
| `D` | sequência demo de ~45 s que reencena a linha do tempo da referência |
| `H` | oculta/mostra a barra de controles |
| `F` | tela cheia |

As abas no canto superior direito são clicáveis: **LUZ** (CINEMA/SUAVE — intensidade do brilho),
**RITMO** (CINEMA/RÁPIDO — velocidade das rotações) e **CÂMERA** (AUTOMÁTICA/FIXA — balanço).

Parâmetros de URL, úteis para screenshots:
`?state=idle|listening|thinking|speaking|face|map` · `&at=<s>` (tempo já decorrido no estado) ·
`&freeze=1` (congela o tempo) · `&q=high|medium|low` · `&ui=0` · `&line=0|1` · `&weather=1` ·
`&level=0..1` (nível de voz simulado, com `freeze`) · `&demo=1`.

## Perfis de qualidade

| Perfil | Para | O que muda |
|---|---|---|
| `high` | GPU dedicada folgada | até 2× DPR, MSAA 4×, bloom em 8 níveis, aberração cromática, cidade 56×56 quadras |
| `medium` (padrão) | GPU intermediária, ex. RTX 2050 / 16 GB em 1080p | DPR até 1,25, bloom em 6 níveis, cidade 44×44 |
| `low` | GPU integrada | sem pós-processamento, 75 % da resolução, cidade 30×30, menos partículas |

Em "Auto", se a média ficar abaixo de ~27 fps por 4 s, o perfil desce um degrau sozinho.
Os perfis **não foram medidos em uma RTX 2050**: foram dimensionados por contagem de
instâncias e custo de shader. Veja "Limitações".

## Como está organizado

```
src/
  state/store.ts      estados, falas demo, parâmetros de URL
  state/rig.ts        valores de animação compartilhados (atualizados a cada frame)
  state/quality.ts    perfis de qualidade
  state/speech.ts     ritmo de revelação das legendas
  scene/Scene.tsx     Canvas + pós-processamento (bloom, vinheta, ruído)
  scene/Director.tsx  transições entre estados e câmera
  scene/Space.tsx     planeta, luzes de cidades, atmosfera e estrelas (shader em tela cheia)
  scene/Canopy.tsx    arco superior e treliça dos cantos (shader)
  scene/Platform.tsx  base circular, pedestal, feixe, partículas
  scene/Core.tsx      núcleo: anéis em camadas, marcadores, ondas, glifo reativo
  scene/FaceScan.tsx  busto em nuvem de pontos (demo)
  scene/City.tsx      cidade procedural instanciada (demo)
  hud/Hud.tsx         relógio, estado, legendas, cartões, painéis do rosto, controles
docs/REFERENCIA_VISUAL.md   análise dos frames, paleta, proporções, checklist de fidelidade
evidence/                   screenshots reais de cada estado + diferenças observadas
scripts/capture.mjs         gera os screenshots (Playwright)
scripts/compare.mjs         monta a página lado a lado com a referência
```

Tudo é gerado por código: não há texturas, modelos, vídeos ou logos de terceiros.
Fontes: Orbitron e Rajdhani (SIL OFL), empacotadas via `@fontsource`.

## Screenshots e comparação

```powershell
npm i -D playwright; npx playwright install chromium   # só na primeira vez
npm run build; npm run preview                         # deixe rodando
npm run capture                                        # em outro terminal → evidence/*.jpg
```

Para a página lado a lado, copie a pasta `reference/` do kit para dentro de `jarvis-hud/`
e rode `npm run compare`. A pasta `reference/` e a página gerada ficam fora do Git de propósito:
são quadros de um vídeo de terceiros, para uso privado.

## Limitações reais

- **Nada é funcional além do visual.** O nível de voz é uma função matemática; o "rosto" é um
  desenho; a cidade é inventada; o relógio é o do sistema.
- **Desempenho não medido em GPU real.** Os screenshots foram gerados em Chromium headless com
  renderização por software. Falta medir fps numa RTX 2050 e ajustar os perfis.
- **O mapa não é fotogrametria.** A referência usa imagem aérea 3D de uma cidade real; aqui são
  blocos procedurais com telhados coloridos. Fidelidade parcial neste estado.
- **Tela curva/ultrawide:** o layout foi acertado em 16:9. Em 21:9 funciona, mas as proporções
  do núcleo em relação à largura mudam.
- **App de navegador, não executável.** Para virar janela própria no Windows falta empacotar
  (Tauri ou Electron) — isso instala software e não foi feito.
- Estado **Pensando** não existe isolado na referência; o visual dele é proposta minha.

## Próximos passos sugeridos (precisam da sua aprovação)

1. Medir fps na sua máquina e calibrar os perfis.
2. Voz local gratuita (Web Speech API do Windows) e microfone alimentando o glifo de verdade.
3. Empacotar como app de desktop.
4. Clima/notícias/mapa com fontes gratuitas — só depois de escolher quais.
