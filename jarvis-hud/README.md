# JARVIS OS 0.2

Assistente pessoal com interface holográfica: um HUD em React + Three.js e um núcleo local em
Python (FastAPI) que conversa pelo Google Gemini, fala, ouve e consulta dados reais do
computador e de Itumbiara-GO.

Esta pasta é independente do CRUD de logística que está na raiz do repositório.

> **Antes de confiar:** a integração com o Gemini foi escrita e testada com um cliente
> simulado, mas **ainda não rodou contra a API real** — não havia chave durante o
> desenvolvimento. Também não foi executada em Windows. O que foi e o que não foi verificado
> está em [`docs/RELATORIO_0.2.md`](docs/RELATORIO_0.2.md).

## O que é real e o que é simulado

| Recurso | Situação |
|---|---|
| Cena holográfica (núcleo, base, feixe, arco, planeta) | Real — igual à 0.1, agora movida por áudio de verdade. |
| Conversa com IA | Gemini, quando há chave em `backend/.env`. Sem chave: modo local com poucos comandos fixos (não é IA). |
| Voz do assistente | Gemini TTS (nuvem) ou voz local do sistema. |
| Fala do usuário | Microfone → transcrição pelo Gemini (nuvem, com consentimento) ou Whisper local opcional. |
| Hora, clima | Reais: fuso `America/Sao_Paulo`; clima do Open-Meteo. |
| CPU, RAM, disco, processos | Reais (psutil). |
| Abrir apps/pastas, volume, rotinas | Reais no Windows, só para itens de `backend/config/permissions.json`. |
| LEDs, persiana, fechadura, robô | **Simuladores.** Nenhum hardware é acionado. |
| Reconhecimento facial | **Demonstração visual.** Nenhuma câmera é usada. |
| Mapa 3D | **Cidade fictícia de demonstração**, identificada na tela. |
| Notícias | Desligadas até você configurar um feed RSS. |

## Iniciar no Windows

Requisitos: [Node.js LTS](https://nodejs.org) e [Python 3.10+](https://www.python.org/downloads/)
(marque "Add python.exe to PATH" ao instalar).

Dê dois cliques em **`INICIAR.bat`**. Na primeira vez ele instala as dependências (alguns
minutos, precisa de internet), compila o HUD, cria `backend\.env` e
`backend\config\permissions.json` a partir dos exemplos, inicia o núcleo e abre
<http://127.0.0.1:8765>. Use Chrome ou Edge; `F` alterna a tela cheia.

Para ativar a IA, coloque sua chave em `backend\.env` (`GEMINI_API_KEY=`) e reinicie —
passo a passo em [`docs/CONFIGURACAO_GEMINI.md`](docs/CONFIGURACAO_GEMINI.md).

<details>
<summary>Iniciar manualmente / modo de desenvolvimento</summary>

```powershell
cd jarvis-hud
npm install
python -m venv backend\.venv
backend\.venv\Scripts\python -m pip install -r backend\requirements.txt
copy backend\.env.example backend\.env
copy backend\config\permissions.example.json backend\config\permissions.json

# terminal 1 — núcleo
cd backend; .venv\Scripts\python -m app.main

# terminal 2 — HUD com recarga automática (http://127.0.0.1:5173, repassa /api e /ws ao núcleo)
npm run dev
```

Sem o núcleo rodando, o HUD abre do mesmo jeito em modo demonstração.
</details>

## Usar

- **Texto:** digite na barra inferior e pressione Enter.
- **Voz:** botão do microfone ou tecla `M`. A gravação termina sozinha após ~1 s de silêncio.
  Com transcrição em nuvem, o HUD pede autorização antes de enviar áudio e mostra o selo NUVEM.
- **Escuta contínua:** Configurações → Áudio. Só reage a frases com a palavra "Jarvis".
- **Interromper:** botão "Parar", `Esc`, ou comece outro comando.
- **Configurações (engrenagem):** IA, voz e mecanismo, velocidade, volume, dispositivos de
  áudio, privacidade, qualidade gráfica e os estados de demonstração.
- **Teclas:** `M` falar · `Esc` parar · `H` ocultar a interface · `F` tela cheia ·
  `1`–`6` estados de demonstração · `D` sequência demo.

À esquerda ficam hora, clima e dispositivos; à direita, o estado da IA e do sistema e a lista
**Comandos executados** (✓ executado, ✕ recusado ou falhou, SIM só no simulador); embaixo, a
transcrição da conversa.

## O que o assistente pode fazer no computador

Somente o que está em `backend/config/permissions.json`: aplicativos (lista fixa de
argumentos, sem shell), pastas e rotinas. A IA escolhe um identificador dessa lista; nunca
envia um comando. Itens com `"confirm": true` pedem um clique de autorização no HUD. Não há
ferramenta de terminal, de arquivos ou de instalação. Detalhes em
[`docs/ARQUITETURA_JARVIS_CORE.md`](docs/ARQUITETURA_JARVIS_CORE.md).

## Qualidade gráfica

| Perfil | Para | O que muda |
|---|---|---|
| `high` | GPU dedicada folgada | até 2× DPR, MSAA 4×, bloom em 8 níveis, cidade 56×56 quadras |
| `medium` (padrão) | GPU intermediária, ex. RTX 2050 em 1080p | DPR até 1,25, bloom em 6 níveis, cidade 44×44 |
| `low` | GPU integrada | sem pós-processamento, 75 % da resolução |

Em "Automática", se a média ficar abaixo de ~27 fps por 4 s, o perfil desce um degrau. Os
perfis não foram medidos em uma RTX 2050. Se o Windows estiver usando a GPU integrada, force a
dedicada em *Configurações → Sistema → Tela → Elementos gráficos* para o navegador.

## Testes

```powershell
# backend — 85 testes, sem rede nem chave
backend\.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd backend; .venv\Scripts\python -m pytest; cd ..

# frontend
npx tsc --noEmit; npm run build

# ponta a ponta em navegador real (núcleo rodando; requer Playwright)
npm i -D playwright; npx playwright install chromium
npm run e2e

# integração real com o Gemini e amostras de voz (requer a chave)
backend\.venv\Scripts\python backend\scripts\check_gemini.py
```

## Estrutura

```
backend/app/            núcleo: main, assistant, ai/, voice/, system/, services/, devices/, memory/, security/
backend/config/         permissions.example.json (lista de apps, pastas e rotinas autorizados)
backend/scripts/        check_gemini.py (verificação da IA e comparação de vozes)
backend/tests/          testes automatizados
src/scene/              cena 3D (Core, Platform, Space, Canopy, City, FaceScan, Director)
src/core/               audio.ts (reprodução, microfone, níveis) · backend.ts (sessão e WebSocket)
src/state/              store.ts (estado visual) · jarvis.ts (estado do assistente) · rig.ts
src/hud/                Hud.tsx · Settings.tsx
scripts/                capture.mjs · compare.mjs · e2e.mjs
docs/                   documentação
evidence/               capturas da 0.1 e da 0.2
```

## Documentação

- [`docs/RELATORIO_0.2.md`](docs/RELATORIO_0.2.md) — auditoria, testes, critérios de aprovação, limitações.
- [`docs/ARQUITETURA_JARVIS_CORE.md`](docs/ARQUITETURA_JARVIS_CORE.md) — módulos, protocolo e segurança.
- [`docs/CONFIGURACAO_GEMINI.md`](docs/CONFIGURACAO_GEMINI.md) — chave, modelos, privacidade e falhas.
- [`docs/VOZ_JARVIS.md`](docs/VOZ_JARVIS.md) — identidade vocal, comparação de vozes, áudio e microfone.
- [`docs/INTEGRACOES_FUTURAS.md`](docs/INTEGRACOES_FUTURAS.md) — dispositivos e mapa real.
- [`docs/REFERENCIA_VISUAL.md`](docs/REFERENCIA_VISUAL.md) — análise do vídeo de referência (0.1).

## Licenças e atribuições

Tudo na cena é gerado por código. Fontes: Orbitron e Rajdhani (SIL OFL). Dados meteorológicos:
[Open-Meteo](https://open-meteo.com) (CC BY 4.0), gratuito para uso não comercial.
