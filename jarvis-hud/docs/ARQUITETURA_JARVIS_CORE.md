# Arquitetura — JARVIS Core 0.2.1

O JARVIS OS tem duas partes que rodam no mesmo computador:

```
┌────────────────────────── navegador (HUD) ──────────────────────────┐
│ React + Three.js: cena holográfica, legendas, painéis, configurações │
│ src/core/audio.ts   reprodução, microfone, medição de nível          │
│ src/core/backend.ts sessão + WebSocket      src/state/jarvis.ts      │
└───────────────▲──────────────────────────────────────┬───────────────┘
        eventos │ WebSocket /ws (token)                 │ REST /api/* (token)
┌───────────────┴──────────────────────────────────────▼───────────────┐
│ JARVIS Core — FastAPI em 127.0.0.1:8765 (backend/app)                │
│ assistant.py  orquestra a conversa                                   │
│ ai/        Gemini (nuvem) · modo local sem IA · ferramentas          │
│ voice/     TTS (Gemini | local) · STT (Gemini | Whisper) · frases    │
│ system/    leituras psutil · ações do Windows (lista aprovada)       │
│ services/  clima Open-Meteo · hora local · notícias RSS              │
│ devices/   interfaces + simuladores   memory/  SQLite                │
│ security/  permissões e autenticação local                           │
└───────────────┬──────────────────────────────────────────────────────┘
                │ HTTPS (só se configurado)
        Gemini API · Open-Meteo · feed RSS escolhido pelo usuário
```

A chave `GEMINI_API_KEY` existe apenas no processo do backend (`backend/.env`). O HUD nunca a
recebe: ele só conhece um token de sessão local.

## Módulos do backend

| Arquivo | Responsabilidade |
|---|---|
| `app/main.py` | Servidor FastAPI, guarda de Host/Origin/token, rotas REST, WebSocket, serve o HUD compilado (`dist/`). |
| `app/config.py` | Lê `backend/.env`. Localização padrão: Itumbiara-GO, `America/Sao_Paulo`, pt-BR. |
| `app/assistant.py` | `Assistant` (orquestrador) e `Connection` (um HUD conectado): turno de conversa, fila de fala, confirmação, voz do usuário. |
| `app/ai/base.py` | Contratos: `AIProvider`, `ChatSession`, `ToolCall`, `ToolOutcome`, `AIError`. |
| `app/ai/gemini_provider.py` | SDK `google-genai` (API `v1beta`): descoberta dos modelos da conta, teste de resposta, streaming, function calling manual, nível de raciocínio por modelo, troca de modelo em falha, cotas lidas do erro 429 e lembradas em `data/gemini_state.json`. |
| `app/ai/local_provider.py` | Modo sem IA: poucas palavras-chave → mesmas ferramentas reais → frases fixas. |
| `app/ai/persona.py` | Instrução de sistema (personalidade e regras de honestidade). |
| `app/ai/tools.py` | Catálogo de ferramentas, validação estrita de argumentos, execução. |
| `app/voice/tts.py` | `TTSEngine`: `GeminiTTS` (streaming, direção de estilo em `speech_metadata.style`, troca de modelo de voz), `LocalTTS` (SAPI5/espeak-ng); `VoiceOutput` escolhe e faz fallback. |
| `app/voice/stt.py` | `STTEngine`: `GeminiSTT` (modelo dedicado de transcrição quando a conta tem), `WhisperSTT`; palavra de ativação. |
| `app/voice/audio_stream.py` | WAV, nível RMS, divisão do texto em frases, limpeza de marcação, normalização para fala (horas, unidades). |
| `app/system/monitor.py` | CPU, RAM, discos, processos, bateria, GPU (nvidia-smi) — leituras reais. |
| `app/system/windows.py` | `SystemController`: abrir app/pasta aprovados, volume (pycaw). Fora do Windows responde "indisponível". |
| `app/services/weather.py` | Open-Meteo com cache, novas tentativas e marcação de dado desatualizado. |
| `app/services/local_info.py` | Data/hora da cidade configurada. |
| `app/services/news.py` | Feed RSS/Atom opcional. |
| `app/devices/registry.py` | `Device`, `DeviceRegistry` e os quatro simuladores. |
| `app/memory/store.py` | SQLite: mensagens, lembranças, ações executadas, ajustes. |
| `app/security/permissions.py` | Lista aprovada (`permissions.json`), classes de ação, `LocalAuth`. |

Cada bloco externo fica atrás de uma interface (`AIProvider`, `TTSEngine`, `STTEngine`,
`SystemController`, `Device`). Trocar o Gemini por outro modelo, ou a voz por outro motor,
significa escrever uma classe nova e registrá-la em `Assistant.__init__` — o resto não muda.

## Um turno de conversa

1. O HUD envia `user_text` (ou `user_audio`, que antes passa pelo STT).
2. `Assistant.run_turn` grava a fala, monta a instrução de sistema (com data/hora locais) e o
   histórico recente, e abre uma sessão no provedor.
3. O provedor emite **texto** (repassado ao HUD como `delta`) e **pedidos de ferramenta**.
4. Cada pedido é validado e executado por `ToolRegistry`; o resultado (`executed`, `simulated`,
   `summary`) vai para o HUD (`tool`), para o SQLite (`actions`) e de volta para a IA.
5. Em paralelo, o texto é cortado em frases. No modo econômico (padrão), a primeira frase vai à
   síntese assim que termina e o restante vai em um único pedido no fim. Cada pedido é
   sintetizado em paralelo e entregue em ordem: em streaming (`audio_start` → `audio_chunk`… →
   `audio_end`) ou como WAV inteiro (`audio`).
6. `speech_done` avisa que não há mais áudio; `turn_end` fecha o turno.

Se o Gemini falhar **antes** de dizer qualquer coisa (rede, cota, modelo, chave), o turno
continua no modo local e o HUD mostra o erro. Depois de texto emitido não há nova tentativa.

## Protocolo do WebSocket

HUD → Core: `user_text {text}` · `user_audio {wav, mode: ptt|wake}` · `interrupt` ·
`confirm {id, approve}` · `refresh {force}`.

Core → HUD:

| Evento | Conteúdo |
|---|---|
| `hello`, `state` | Retrato do sistema: IA, voz, permissões, dispositivos, localização. |
| `phase` | `thinking`, `transcribing`, `idle`. |
| `transcript` | Fala do usuário (texto digitado ou transcrito, com o motor usado). |
| `delta` | Pedaço da resposta. |
| `tool` | `stage: start|end`, `executed`, `simulated`, `summary`. |
| `audio_start` | Início de um trecho em streaming: `text`, `rate` (Hz), `engine`, `voice`, `model`, `cloud`. |
| `audio_chunk` | Pedaço do trecho: `pcm` (16 bits mono little-endian, base64). |
| `audio_end` | Fim do trecho: `duration`. |
| `audio` | Trecho inteiro (voz local ou reserva): `text`, `wav` (base64), `duration`, `engine`, `voice`, `cloud`. |
| `speech_done`, `turn_end` | Fim do áudio e do turno (`mode: ai|local`, `interrupted`, `error`, `timings` com 1º texto, 1ª voz e total). |
| `error`, `notice` | Falha (`scope: ai|tts|stt`, `code`, mensagem) ou aviso. |
| `confirm_request`, `confirm_closed` | Pedido de autorização para uma ação. |
| `system`, `weather`, `news`, `devices` | Leituras periódicas. |
| `ui` | Ação visual pedida pela IA (`show_map`). |
| `stt_empty`, `wake_ignored` | Gravação sem fala; fala sem a palavra de ativação. |

## Segurança

- **Só localhost.** O servidor escuta em `127.0.0.1`.
- **Host, Origin e token.** Toda rota `/api/*` e o `/ws` validam o cabeçalho `Host` (contra
  DNS rebinding) e o `Origin` (contra páginas web tentando falar com o localhost). O token de
  sessão é entregue por `POST /api/session` apenas a origens permitidas e exigido em todo o
  resto. Outro programa já rodando na sua conta do Windows não é barrado por isso — nenhum
  serviço local consegue.
- **A IA não executa nada.** Ela devolve o nome de uma ferramenta e argumentos; o backend
  valida contra um esquema fechado (tipos, enumerações, limites, sem campos extras).
- **Sem shell.** Aplicativos são uma lista fixa de argumentos em `permissions.json`, iniciados
  sem interpretador de comandos. Entradas com `& | ; < >` são descartadas na carga.
- **Confirmação.** Itens com `"confirm": true` só rodam após um clique no HUD (45 s de prazo).
- **Fechadura.** `unlock` é sempre recusado, inclusive no simulador.
- **Privacidade.** Áudio só vai à nuvem após consentimento explícito gravado nos ajustes.

## Estado no HUD

`src/state/store.ts` continua dono do estado visual (`idle`, `listening`, `thinking`,
`speaking`, `face`, `map`). O campo `demo` separa os dois mundos:

- `demo = false`: quem troca o estado são os eventos reais; `rig.level` vem do analisador de
  áudio da fala reproduzida e `rig.mic` do microfone.
- `demo = true`: falas `LINES`/`MAP_BRIEFING` e envelope simulado, sempre com o selo DEMO.

## Testes

`backend/tests` (117 testes, sem rede nem chave): serviços, permissões, ferramentas, provedor
Gemini com cliente falso construído com os tipos do próprio SDK, orquestração, voz e API.
`scripts/e2e.mjs` exercita o sistema inteiro em um navegador real.
