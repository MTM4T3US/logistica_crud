# Relatório — JARVIS OS 0.2

Ambiente em que tudo abaixo foi executado: contêiner Linux, Python 3.13, Node 22, Chromium
headless com renderização por software. **Sem Windows, sem microfone físico, sem GPU e sem
chave do Gemini.** O que depende disso está marcado como não verificado.

## Etapa A — Auditoria do projeto 0.1

| Item | Resultado |
|---|---|
| Estrutura | React 19 + TypeScript + Vite 8; Three.js 0.187 via React Three Fiber 9; Zustand 5; pós-processamento `postprocessing` 6. |
| Build antes das mudanças | `tsc --noEmit` sem erros; `vite build` em 0,4 s; pacote JS de 1 282 kB (352 kB gzip). |
| Estados | `idle`, `listening`, `thinking`, `speaking`, `face`, `map`, todos dirigidos por `Director.tsx` a partir de `store.ts`. |
| Dependência de conteúdo simulado | `LINES` e `MAP_BRIEFING` definiam fala, legenda e duração; `rig.level` era uma função matemática. |
| Backend | Inexistente. |
| Rede | `api.open-meteo.com` estava bloqueado na política do ambiente; foi liberado em um ambiente próprio do repositório. |
| Cópia de segurança | Estado 0.1 preservado no commit `c24ce72` (tag local `jarvis-hud-0.1`; o envio da tag ao GitHub foi recusado pelo proxy de Git desta sessão). |

## Testes automatizados

`backend\.venv\Scripts\python -m pytest` → **85 testes, todos passando** (2,7 s). Nenhum usa
rede ou chave: o Gemini é substituído por um cliente falso que devolve objetos dos tipos do SDK.

| Arquivo | Testes | Cobre |
|---|---|---|
| `test_core_services.py` | 14 | Configuração (Itumbiara por padrão, chave fora de `repr`, `.env` ignorado, chave ausente do código React), permissões, autenticação local, memória, clima (dados reais não inventados, cache, repetição, dado desatualizado), hora no fuso, notícias, simuladores (fechadura, robô). |
| `test_tools.py` | 10 | Validação estrita, catálogo só com o autorizado, lista aprovada, confirmação, falha honesta fora do Windows, ausência de shell, leituras reais do sistema, memória opcional. |
| `test_gemini_provider.py` | 21 | Streaming, histórico, ida e volta de function calling (preservando assinaturas de raciocínio), 10 mapeamentos de erro, repetição, modelo reserva, sem repetição após texto emitido, tempo esgotado, resposta vazia/bloqueada, escolha de modelo. |
| `test_voice.py` | 18 | WAV, divisão em frases, limpeza de marcação, palavra de ativação, Gemini TTS/STT (cliente falso), escolha e fallback de motor, voz local real (espeak-ng). |
| `test_assistant.py` | 14 | Turno completo, ferramentas registradas, confirmação, laço de ferramentas interrompido, queda para o modo local, voz por frase, fallback de voz, interrupção, consentimento para nuvem, silêncio, palavra de ativação, ajustes. |
| `test_api.py` | 8 | Token obrigatório, Host/Origin, CORS, WebSocket recusado sem credenciais, conversa real pelo WebSocket com ferramentas. |

Frontend: `npx tsc --noEmit` sem erros; `npm run build` em 0,45 s (1 316 kB, 363 kB gzip).

## Demonstração ponta a ponta

`npm run e2e` com o backend real rodando (modo local, sem chave) → **14 de 14 verificações**.
Capturas em `evidence/0.2/`.

| Verificação | Resultado observado |
|---|---|
| HUD conectado com token de sessão | "NÚCLEO ONLINE · MODO LOCAL (SEM IA)" |
| Relógio no fuso de Itumbiara | HUD 07:13 quando o horário de `America/Sao_Paulo` era 07:13 (UTC 10:13) |
| Clima de fonte real | "24° · Quase sem nuvens · Sensação 27° · Umidade 87% … Open-Meteo · atualizado às 07:14" |
| Leitura real do sistema | "CPU 70% · RAM 5% · DISCO 24%" (CPU alta por causa da renderização por software) |
| Ferramenta executada e exibida | "✓ Estado do computador — CPU 91,8% · RAM 5,6% · disco 24,1% usado" |
| Transcrição da conversa real | pergunta digitada + resposta gerada |
| Núcleo reage ao áudio reproduzido | 28 amostras de `rig.level` durante a fala, 19 valores distintos, pico 1,00 |
| Ordem dos estados | PROCESSANDO → JARVIS FALANDO → EM ESPERA |
| Microfone com indicador | "● MICROFONE CAPTURANDO" (um WAV sintético fez o papel do microfone) |
| Anéis reagem ao microfone | `rig.mic` com pico 1,00 |
| Gravação encerrada por silêncio e enviada | o núcleo respondeu "Nenhum motor de transcrição disponível…" (não há STT sem chave) |
| Configurações | IA, Áudio, Privacidade, Desempenho, Demonstração |
| Erros de JavaScript | nenhum |

Regressão visual: as capturas da demonstração (`04-falando`, `07-rosto-confirmado`,
`10-mapa-briefing`) foram refeitas com o código 0.2 e comparadas lado a lado com as da 0.1.
Cena, câmera, núcleo e efeitos são os mesmos; mudaram só os textos do selo e do relógio.

## Critérios de aprovação

| # | Critério | Situação |
|---|---|---|
| 1 | HUD original continua funcionando | ✅ Verificado (regressão visual e sequência demo). |
| 2 | Conversar por texto com o Gemini | ⚠️ **Não verificado.** Implementado e testado com cliente falso; nunca rodou contra a API real por falta de chave. A conversa por texto em si funciona (modo local). |
| 3 | Microfone captura com permissão | ✅ No navegador, com dispositivo falso. ⚠️ Microfone físico não testado. |
| 4 | Resposta com áudio real e voz selecionável | ✅ Voz local (espeak-ng em Linux). ⚠️ Gemini TTS e vozes SAPI do Windows não testados. |
| 5 | Núcleo reage ao áudio verdadeiro | ✅ Medido. |
| 6 | Transcrições correspondem à conversa | ✅ Texto. ⚠️ Fala → texto depende de um motor STT (Gemini ou Whisper), nenhum testado aqui. |
| 7 | Dados de Itumbiara de fonte real | ✅ Open-Meteo, respostas reais durante os testes. |
| 8 | Informações do Windows consultadas de verdade | ✅ Leituras reais via psutil — executadas em Linux. ⚠️ Não rodei em Windows. |
| 9 | API protegida no backend | ✅ Testes de chave, token, Host e Origin. |
| 10 | Funciona sem LEDs, persiana ou robô | ✅ |
| 11 | Testes e build executados | ✅ |
| 12 | Limitações documentadas | ✅ Este arquivo. |

**Conclusão:** pelos critérios da missão, ela **não está concluída** enquanto o item 2 não for
confirmado com uma chave real. Os itens 3, 4, 6 e 8 também precisam de uma passada no seu PC.

## O que ainda é simulado ou não foi feito

- **Dispositivos** (LEDs, persiana, fechadura, robô): só simuladores.
- **Reconhecimento facial:** continua sendo a demonstração visual; nenhuma câmera é usada.
- **Mapa:** cidade fictícia, identificada na tela. Mapa real de Itumbiara não implementado.
- **Notícias:** desligadas até você configurar um feed.
- **Gemini Live API:** não integrada.
- **Comparação de vozes Charon/Orus:** não realizada; há um script para fazê-la.
- **Modo local:** não é IA — reconhece poucas palavras-chave.

## Não verificado nesta entrega

- Qualquer chamada real ao Gemini (conversa, ferramentas, voz, transcrição) e os nomes de
  modelo padrão.
- `INICIAR.bat`, abertura de aplicativos/pastas, controle de volume (pycaw) e vozes SAPI.
- Microfone físico, cancelamento de eco na prática e a escuta contínua com transcrição real.
- Whisper local.
- Desempenho gráfico e latência de voz em uma RTX 2050.

## Observações de comportamento

- O Open-Meteo respondeu HTTP 429 ("limite diário") de forma intermitente a partir do IP
  compartilhado deste ambiente de nuvem. O serviço repete a consulta até três vezes e, sem
  resposta, mostra "Sem dados de clima" em vez de um valor. No seu IP residencial isso não
  deve ocorrer no uso normal (uma consulta a cada 10 minutos).
- Na escuta contínua com transcrição em nuvem, toda fala detectada é enviada ao Google.
- Interromper o assistente apenas falando por cima não funciona; use o botão, `Esc` ou o
  botão de falar.

## Como validar no seu computador

1. Dois cliques em `INICIAR.bat`. Confira no HUD: relógio, clima de Itumbiara, CPU/RAM/disco.
2. Digite "como está meu computador?" — deve responder com voz (modo local).
3. Coloque a chave em `backend\.env`, reinicie e rode `scripts\check_gemini.py`
   (ver `docs/CONFIGURACAO_GEMINI.md`).
4. No HUD: "Jarvis, bom dia", depois "prepara tudo para programar" (pede confirmação).
5. Botão de falar: autorize o envio de áudio e diga um comando.
6. Compare as vozes e escolha (ver `docs/VOZ_JARVIS.md`).
