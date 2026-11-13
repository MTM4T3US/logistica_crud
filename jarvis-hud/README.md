# JARVIS OS 0.6

Assistente pessoal com interface holográfica: um HUD em React + Three.js e um núcleo local em
Python (FastAPI) que conversa pelo Google Gemini, fala, ouve e consulta dados reais do
computador e de Itumbiara-GO.

Esta pasta é independente do CRUD de logística que está na raiz do repositório.

> **Estado (0.6):** escrita em Linux na nuvem (318 testes automáticos do núcleo e o teste de navegador com 17
> verificações). As versões 0.3 a 0.5.2 já foram testadas no seu Windows pelo outro chat; o app da bandeja,
> as cenas e o HUD novo da 0.6 ainda não. Roteiro: [`docs/PROMPT_TESTE_WINDOWS.md`](docs/PROMPT_TESTE_WINDOWS.md);
> o que mudou e o que falta: [`docs/RELATORIO_0.6.md`](docs/RELATORIO_0.6.md).

## O que é real e o que é simulado

| Recurso | Situação |
|---|---|
| Cena holográfica (núcleo, base, feixe, arco, planeta) | Real — igual à 0.1, agora movida por áudio de verdade. |
| Conversa com IA | Gemini, quando há chave em `backend/.env`. Comandos conhecidos passam pelo **roteador local** e não gastam cota. Sem chave/cota/internet: só comandos locais (não é IA). |
| Voz do assistente | Gemini TTS em streaming (nuvem; escolha entre ~30 vozes e 4 interpretações) ou voz local do sistema. |
| Fala do usuário | Botão de falar ou escuta contínua: "Jarvis" detectado **no PC** (openWakeWord); transcrição local (Whisper) ou Gemini com consentimento. |
| Hora, clima | Reais: fuso `America/Sao_Paulo`; clima do Open-Meteo. |
| CPU, RAM, disco, processos | Reais (psutil). |
| Abrir apps/pastas/projetos, volume, mídia, janelas, rotinas | Windows, só para itens de `backend/config/permissions.json` (não testado em Windows ainda). |
| LEDs | Driver real ELK-BLEDDM por Bluetooth (`JARVIS_LEDS=bluetooth`) ou simulador (padrão). Não testado com a fita ainda. |
| Persiana, robô | **Simuladores.** Nenhum hardware é acionado. |
| Entrada por rosto | Real, no navegador: câmera local, malha de 468 pontos, piscar, descritor comparado pelo núcleo; PIN reserva. Nenhuma imagem é gravada. Na demonstração (teclas 1–6) continua encenada e marcada DEMO. |
| Música de entrada | Arquivo do próprio usuário, guardado só no PC; abaixa sob a voz. |
| Computador (0.5) | Qualquer programa instalado, sites, arquivos, digitar/atalhos, captura, brilho, bloquear/suspender/desligar (com confirmação). Sem terminal. |
| Computer use (0.5) | Vê a tela e usa mouse/teclado via Gemini (autorização por tarefa; ~1 pedido de IA por passo). |
| Agenda (0.5) | Local; frases em português; lembretes; dita nas boas-vindas. |
| Luzes de casa (0.5) | Smart Life/Tuya pela rede local (as lâmpadas confirmam). Configuração: `CONFIGURAR_LUZES.bat`. |
| Fechadura (0.5) | Só trancar e ver o estado, protocolo assinado ([`docs/FECHADURA.md`](docs/FECHADURA.md)); simulador até parear. |
| App do Windows (0.6) | Ícone na bandeja, iniciar com o Windows, atalhos globais (`Ctrl+Alt+J` abre, `Ctrl+Alt+Espaço` fala), janela própria sem barra do navegador. |
| Cenas (0.6) | "Bom dia", "modo cinema", "modo foco", "boa noite", "estou saindo": luzes de casa + fita + volume + porta + resumo, por voz, botão ou horário. |
| Mapa 3D | Itumbiara real (OpenStreetMap, baixado uma vez e guardado no PC). Sem o mapa baixado: cidade fictícia, identificada na tela. |
| Notícias | Google Notícias de Itumbiara e do Brasil (feeds RSS, sem inventar manchetes). `JARVIS_NEWS_FEEDS=off` desliga. |

## Iniciar no Windows

Requisitos: [Node.js LTS](https://nodejs.org) e [Python 3.10+](https://www.python.org/downloads/)
(marque "Add python.exe to PATH" ao instalar).

Na primeira vez, dê dois cliques em **`INICIAR.bat`**. Ele instala as dependências (alguns minutos, precisa de
internet), compila o HUD, cria `backend\.env` e `backend\config\permissions.json` a partir dos exemplos,
inicia o núcleo e abre <http://127.0.0.1:8765>. Use Chrome ou Edge; `F` alterna a tela cheia.

Depois, use o **app** (0.6):

1. Dois cliques em **`INSTALAR_ATALHOS.bat`** (uma vez): cria o atalho **JARVIS** na Área de Trabalho e no Menu
   Iniciar e pergunta se ele deve iniciar com o Windows.
2. Abra pelo atalho (ou **`JARVIS.bat`**). O núcleo roda escondido, aparece um ícone na bandeja (perto do relógio)
   e o HUD abre numa janela própria.
3. Em qualquer programa: **`Ctrl+Alt+J`** traz o JARVIS, **`Ctrl+Alt+Espaço`** fala com ele. Clique direito no
   ícone da bandeja: abrir, falar, bloquear, iniciar com o Windows, sair.
4. "Iniciar com o Windows" também fica em Configurações → Sistema. Ao iniciar com o Windows, só o ícone aparece; o
   HUD abre pelo atalho. Registro em `backend\data\jarvis.log`.

O `INICIAR.bat` continua valendo para instalar, atualizar e ver o núcleo num console.

Para ativar a IA:

1. Crie uma chave em <https://aistudio.google.com/apikey> (não precisa de faturamento).
2. Abra `backend\.env` no Bloco de Notas e cole a chave logo após `GEMINI_API_KEY=`. Salve.
3. Feche e abra o `INICIAR.bat` de novo. O selo no topo do HUD passa a mostrar **IA GEMINI**.
4. Opcional: dois cliques em **`VALIDAR_GEMINI.bat`** para testar tudo com a sua chave e gerar
   amostras de voz em `backend\samples\`.

A chave fica só nesse arquivo, que não vai para o Git. Não a cole em conversas; se colar, apague-a
no AI Studio e crie outra. Passo a passo em [`docs/CONFIGURACAO_GEMINI.md`](docs/CONFIGURACAO_GEMINI.md).

**Cotas do nível gratuito (medidas):** 5 pedidos por minuto e 20 por dia, por modelo. O núcleo
alterna entre os modelos da conta, o que rende algumas dezenas de respostas faladas por dia.

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

## Entrada (0.4)

1. Configurações → **ENTRADA POR ROSTO**: defina um PIN reserva e clique **Cadastrar meu rosto** (pisque uma
   vez e vire o rosto de leve).
2. Configurações → **MÚSICA DE ENTRADA**: escolha um arquivo de música seu.
3. Ao abrir o JARVIS: **Iniciar reconhecimento** → olhe e pisque → música → boas-vindas → a câmera voa
   para Itumbiara e ele fala o clima e as notícias.
4. Para bloquear: "Jarvis, bloqueia o Jarvis" ou o botão nas Configurações. Desbloquear é só com rosto ou PIN.

A entrada por rosto protege o JARVIS de quem senta no seu computador; não substitui a senha do Windows
e nunca serve para a fechadura.

## Usar

- **Texto:** digite na barra inferior e pressione Enter.
- **Voz:** botão do microfone ou tecla `M`. A gravação termina sozinha após ~1 s de silêncio.
  Com transcrição em nuvem, o HUD pede autorização antes de enviar áudio e mostra o selo NUVEM.
- **Escuta contínua:** Configurações → Áudio. Só reage a frases com a palavra "Jarvis".
- **Interromper:** botão "Parar", `Esc`, ou comece outro comando.
- **Botões (0.6):** à direita, **CENAS** (um toque roda a cena; as que pedem confirmação mostram CONFIRMA) e
  **CASA** (acender/apagar, ver e trancar a porta, modo trancado). Cada botão passa pelo mesmo caminho de um
  comando falado: mesmas confirmações, registro e resposta, sem gastar o Gemini.
- **Configurações (engrenagem), em abas:** Geral (estado, IA, privacidade), Voz (vozes, microfone, escuta
  contínua), Casa (cenas e horários, luzes, dispositivos), Entrada (rosto, música), Agenda e Sistema (app do
  Windows, desempenho, demonstração).
- **Histórico (relógio no topo ou `L`):** a conversa e todos os avisos, lembretes e ações desta sessão.
- **Ajuda (`?`):** atalhos e exemplos do que dizer.
- **Teclas:** `M` falar · `Ctrl+M` microfone · `Esc` parar/fechar · `L` histórico · `?` ajuda · `H` ocultar a
  interface · `F` tela cheia · `1`–`6` estados de demonstração · `D` sequência demo.

À esquerda ficam clima, agenda do dia e dispositivos; à direita, cenas, casa e **Comandos executados**
(✓ executado, ✕ recusado ou falhou, SIM só no simulador); nos cantos, hora e estado do sistema; embaixo, a
conversa. Lembretes e cenas agendadas aparecem em destaque no topo.

## Cenas (0.6)

| Cena | Diga | O que faz |
|---|---|---|
| Bom dia | "bom dia" (só a frase) | luzes de casa brancas, fita quente, resumo do clima, notícias e agenda |
| Modo cinema | "modo cinema", "hora do filme" | apaga a casa, fita em modo cinema, volume 35 |
| Modo foco | "modo foco", "vamos trabalhar" | luz branca, fita branca 80%, volume 20 |
| Boa noite | "boa noite" (só a frase) | apaga tudo, tranca a porta, diz a agenda de amanhã |
| Saindo de casa | "estou saindo" | **pede confirmação**; apaga tudo, modo trancado na porta, bloqueia o Windows |

- **Horário:** Configurações → Casa → CENAS: hora, dias (todos, dias úteis, fim de semana) e ligar/desligar.
  Roda uma vez por dia com o JARVIS aberto. Cenas que pedem confirmação só avisam no horário.
- **Bloqueado:** a cena agendada roda, mas ele só cumprimenta; clima, notícias e agenda ficam para depois do rosto.
- **Sem um recurso** (ex.: sem lâmpadas Tuya), a etapa é pulada e ele diz quantas foram puladas.
- **Mudar uma cena:** crie em `permissions.json` uma rotina com o mesmo id (ex.: `"cinema"`). `"cenas_padrao": false`
  desliga as prontas. Nenhuma cena destranca a porta.

## O que o assistente pode fazer no computador

Desde a 0.5: abrir qualquer programa instalado (pelo Menu Iniciar), sites e pesquisas, páginas das
Configurações do Windows, arquivos das suas pastas pessoais (abrir, mostrar, Lixeira), digitar e atalhos,
captura de tela, brilho, bloquear, suspender, desligar e reiniciar. Fechar programas, Lixeira, desligar e
atalhos que fecham **pedem confirmação**. Nunca: terminal, digitar em terminal ou no Executar, executar
arquivos `.exe`/scripts, encerrar processos do sistema. Cada grupo pode ser desligado em
`permissions.json` → `pc_control`. A IA nunca envia um comando de sistema: escolhe uma ferramenta da lista,
e o núcleo confere. Detalhes em [`docs/ARQUITETURA_JARVIS_CORE.md`](docs/ARQUITETURA_JARVIS_CORE.md) e
[`docs/RELATORIO_0.5.md`](docs/RELATORIO_0.5.md).

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
# backend — sem rede nem chave
backend\.venv\Scripts\python -m pip install -r backend\requirements-dev.txt
cd backend; .venv\Scripts\python -m pytest; cd ..

# frontend
npx tsc --noEmit; npm run build

# ponta a ponta em navegador real (núcleo rodando; requer Playwright)
npm i -D playwright; npx playwright install chromium
npm run e2e

# integração real com o Gemini e amostras de voz (requer a chave; gasta cota)
VALIDAR_GEMINI.bat
```

## Estrutura

```
backend/app/            núcleo: main, assistant, desktop_app (bandeja), ai/, voice/, system/, services/, devices/, memory/, security/
backend/jarvis_app.pyw  app do Windows (pythonw, sem console): bandeja, atalhos globais, iniciar com o Windows
backend/config/         permissions.example.json (lista de apps, pastas e rotinas autorizados)
backend/scripts/        validar_gemini.py · diagnostico.py · baixar_modelos.py · teste_led.py · baixar_mapa.py
backend/tests/          testes automatizados
src/scene/              cena 3D (Core, Platform, Space, Canopy, City, FaceScan, Director)
src/core/               audio.ts (reprodução, microfone, níveis) · backend.ts (sessão e WebSocket)
src/state/              store.ts (estado visual) · jarvis.ts (estado do assistente) · rig.ts
src/hud/                Hud.tsx · Panels.tsx (cenas, histórico, ajuda) · Settings.tsx (abas) · icons.tsx
scripts/                capture.mjs · compare.mjs · e2e.mjs
docs/                   documentação
evidence/               capturas da 0.1, 0.2 e 0.2.1; amostras de voz em evidence/0.2.1/vozes
```

## Documentação

- [`docs/RELATORIO_0.6.md`](docs/RELATORIO_0.6.md) — app do Windows, cenas da casa e o HUD novo.
- [`docs/RELATORIO_0.5.md`](docs/RELATORIO_0.5.md) — computador, computer use, agenda, luzes de casa e fechadura.
- [`docs/FECHADURA.md`](docs/FECHADURA.md) — protocolo da fechadura própria (só trancar e ver).
- [`docs/RELATORIO_0.4.md`](docs/RELATORIO_0.4.md) — entrada por rosto, música, resumo e mapa reais: o que foi testado e como.
- [`docs/RELATORIO_0.3.md`](docs/RELATORIO_0.3.md) — o que a 0.3 fez, status por item (real, só API, dublê, simulado, pendente).
- [`docs/WINDOWS_0.3.md`](docs/WINDOWS_0.3.md) — instalação e uso no Windows; [`docs/PROMPT_TESTE_WINDOWS.md`](docs/PROMPT_TESTE_WINDOWS.md) — roteiro de teste no PC.
- [`docs/RELATORIO_0.2.1.md`](docs/RELATORIO_0.2.1.md) — testes reais, problemas corrigidos, cotas, pendências da 0.3.
- [`docs/RELATORIO_0.2.md`](docs/RELATORIO_0.2.md) — auditoria e testes da versão anterior.
- [`docs/ARQUITETURA_JARVIS_CORE.md`](docs/ARQUITETURA_JARVIS_CORE.md) — módulos, protocolo e segurança.
- [`docs/CONFIGURACAO_GEMINI.md`](docs/CONFIGURACAO_GEMINI.md) — chave, modelos, privacidade e falhas.
- [`docs/VOZ_JARVIS.md`](docs/VOZ_JARVIS.md) — identidade vocal, comparação de vozes, áudio e microfone.
- [`docs/INTEGRACOES_FUTURAS.md`](docs/INTEGRACOES_FUTURAS.md) — dispositivos e mapa real.
- [`docs/REFERENCIA_VISUAL.md`](docs/REFERENCIA_VISUAL.md) — análise do vídeo de referência (0.1).

## Licenças e atribuições

Tudo na cena é gerado por código. Malha do rosto: modelo canônico do MediaPipe Face Mesh (Google,
Apache 2.0). Reconhecimento facial: [Human](https://github.com/vladmandic/human) (MIT) e os modelos que
ele inclui. Mapa: © colaboradores do [OpenStreetMap](https://www.openstreetmap.org/copyright) (ODbL).
Notícias: Google Notícias (RSS). Luzes: [tinytuya](https://github.com/jasonacox/tinytuya) (MIT). Fontes: Orbitron e Rajdhani (SIL OFL). Dados meteorológicos:
[Open-Meteo](https://open-meteo.com) (CC BY 4.0), gratuito para uso não comercial.
