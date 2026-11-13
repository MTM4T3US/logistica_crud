# Relatório — JARVIS OS 0.3 no Windows

Data: 12/11/2026, 18:30–19:40 e 22:45–23:25 (pausa por limite de uso). As fases de voz, microfone, sem internet e
desempenho **não foram feitas na 0.3**: o usuário recebeu a 0.4 e elas passam a ser testadas nela (ver `RELATORIO_WINDOWS_0.4.md`).

**PC real (não é o esperado Windows 10/i7):** Windows 11 Pro 10.0.22621 · AMD Ryzen 7 7435HS (8 núcleos/16 threads) ·
15,8 GB RAM · NVIDIA RTX 2050 4 GB (driver 581.15) · ASUS TUF A15 · Realtek Bluetooth (LE ok) ·
Python 3.11.9 (`python`) / 3.12.3 (`py -3`, usado no venv) · Node 24.14.1 · npm 11.11.0.

## 1. Tabela de testes

| Fase | Teste | Status | Evidência |
|---|---|---|---|
| 1 | Ambiente (python, node, npm, nvidia-smi, SO, CPU, RAM, BT) | REAL-OK | valores acima; `Get-PnpDevice` mostra "Realtek Bluetooth Adapter" e "Enumerador LE" OK |
| 1 | `INICIAR.bat` (npm install, build, venv, núcleo) | REAL-OK | porta 8765 livre antes; núcleo 0.3.0 respondeu `/api/health`; HUD mostra "JARVIS OS 0.3 · NÚCLEO ONLINE · IA GEMINI" |
| 1 | `INSTALAR_RECURSOS_LOCAIS.bat` | REAL-FALHOU → corrigido | "NÃO ENCONTRADO hey_jarvis_v0.1.onnx" (openwakeword 0.6 não traz modelos); após correção: "Tudo pronto." |
| 1 | `DIAGNOSTICO.bat --procurar-leds --ble` | REAL-FALHOU → corrigido | BLE: "BleakError: Thread is configured for Windows GUI…"; Piper "nenhuma em piper". Depois: fita `BE:27:53:00:BC:1B · ELK-BLEDDM · -48 dBm`, Piper e Whisper OK (`backend/data/diagnostico-20261112-192826.md`) |
| 1 | STATUS: conexão, modelo, voz, transcrição | REAL-OK | API `/api/state`: gemini-2.5-flash, TTS gemini-3.8-flash-tts, STT whisper (local), wake openWakeWord disponível |
| 1 | `VALIDAR_GEMINI.bat --rapido` | NÃO-TESTADO | não rodado para poupar cota (já havia uso no dia: gemini-3.8-flash-tts com limite diário 10 esgotado) |
| — | `pytest -q` | REAL-OK | 169 passed, 2 skipped (sem amostra real de ativação; sem espeak-ng). Uma rodada isolada teve 1 falha de tempo (0,141 s vs limite 0,14 s; relógio do Windows ~16 ms) — limite ajustado; 7 rodadas seguidas sem falha |
| — | `npm run build` | REAL-OK | "✓ built" |
| 2 | Amostras de voz / escolha / tempos / Piper ouvido pelo usuário | NÃO-TESTADO | limite de uso atingido antes |
| 3 | Microfone, escuta contínua, interrupção, eco, ruído | NÃO-TESTADO | idem |
| 3 | Detector "Jarvis" com voz **sintética** (Piper) | SIMULADO | "Jarvis, que horas são?" 0,000 (ignora); "Hey Jarvis, abre a calculadora." 0,643 (dispara); frases sem a palavra ≤ 0,001. **Risco:** o modelo hey_jarvis pode exigir "Hey". Validar com a voz real. |
| 3 | Whisper local (fala sintética) | SIMULADO | após correção: 1,5–1,7 s na CPU, texto exato "Jarvis, coloque os LEDs em azul e o volume em 20." |
| 4 | Router sem Gemini (chat): que horas são, volume 30, clima, LEDs azul, abre VS Code | REAL-OK | `turn_end.mode = "router"`, provider "roteador" |
| 4 | Router e voz | REAL-FALHOU → corrigido | resposta de comando gastava 1–2 pedidos de Gemini TTS; agora usa Piper em "Automático" (escolha do usuário) |
| 4 | "próxima música" | NÃO-TESTADO | precisa de Spotify/YouTube tocando |
| 4 | Sem internet | NÃO-TESTADO | usuário escolheu simular só no núcleo (proxy inválido); não houve tempo |
| 5 | Abrir calculadora / VS Code / Edge | REAL-OK | "aberto" só depois da janela; conferido com EnumWindows independente: "Calculadora", "Documents - Visual Studio Code", "Nova guia … Microsoft Edge" |
| 5 | "abre o projeto jarvis" | REAL-OK | com o caminho antigo, falha honesta ("A pasta … não existe"); após ajustar `permissions.json`: janela "jarvis-hud - Visual Studio Code" |
| 5 | volume 20 / aumenta / mudo / tira o mudo | REAL-OK | pycaw lido após cada comando: 20 % → 30 % → mudo True → mudo False |
| 5 | lado a lado / minimiza navegador / maximiza código | REAL-OK | retângulos e estados das janelas conferidos (Edge 960×1011 à direita; Edge "min"; Code "max") |
| 5 | "prepara tudo para programar" | REAL-OK | pediu "Executar a rotina “Preparar ambiente de programação” (3 etapas)?"; aprovado: VS Code + Windows Terminal reais, luzes no simulador |
| 5 | "fecha o bloco de notas" (close_windows=true) | REAL-OK (só a confirmação) | pediu confirmação nomeando “.env - Bloco de notas”; **recusei de propósito** (era o .env aberto); janela continuou aberta |
| 5 | pausa/próxima música | NÃO-TESTADO | sem mídia tocando |
| 6 | Scripts antigos vs driver | REAL-OK | `led_test_blue.py` e `led_bridge.py` usam exatamente os bytes e o UUID FFF3 do driver. Outros scripts (`Desktop\teste_led.py`, `JARVIS_Desktop_v1\led_ble.py`) usam a variante de cor `7e 07 05 03 RR GG BB 10 ef` — não necessária |
| 6 | `TESTAR_LED.bat` básico (ligar, azul, desligar) | REAL-OK | usuário respondeu SIM nos 3 (`backend/data/teste-led-20261112-193100.md`) |
| 6 | `--completo --inspecionar` (azul, vermelho, verde, branco, branco 30 %, desligar) | REAL-OK | SIM nos 8 passos; características: 2a00, fff4 (notify), fff3 (read, write-without-response) (`teste-led-20261112-193340.md`) |
| 6 | JARVIS → conectar (`/api/devices/leds/connect`) | REAL-OK | "Conectado à fita BE:27:53:00:BC:1B" em ~2 s |
| 6 | "coloque os LEDs em azul" | REAL-OK | usuário: "sim" (cor enviada #0050ff) |
| 6 | "LEDs em vermelho" | REAL-OK | usuário: "sim" |
| 6 | "desligue as luzes" | REAL-OK | usuário: "sim" (23:04:50) — mas a resposta falada acendia a fita de novo pelo efeito de voz; corrigido |
| 6 | "ativar modo cinema" (fita alcançável) | REAL-OK | 2 de 2 etapas; volume real 35 %; usuário: azul escuro e fraco, "sim" |
| 6 | "ativar modo cinema" (fita fora de alcance) | REAL-FALHOU → corrigido | 1 de 2 etapas e o JARVIS disse "Rotina executada"; levou 86 s. Agora diz "Só em parte… Falhou: …" |
| 6 | "brilho em 30%" | REAL-FALHOU → corrigido → REAL-OK | foi ao Gemini, que respondeu "comando enviado" **sem chamar ferramenta** (nada executado). Agora vai pelo roteador: vermelho → #4c0000; usuário: "sim" |
| 6 | Fita desconectada (fora da tomada) | REAL-FALHOU → corrigido → REAL-OK | antes: falha em 82 s com "BleakDeviceNotFoundError…"; agora: 25,6 s, "A fita de LED não respondeu… Ela está na tomada…?"; `/api/health` respondeu em 4 ms durante a falha (HUD não trava) |
| 6 | Religada → reconexão automática | REAL-OK | "LEDs em verde" reconectou e enviou em 2,6 s; usuário: "sim" |
| 6 | "volume 30" + "LEDs em azul" em 0,5 s | REAL-OK | ambos executados (0,85 s de diferença), volume real 30 %, usuário viu o azul |
| 6 | **Efeito de abertura** (novo, pedido do usuário) | REAL-OK | ao iniciar o núcleo: acende em azul aos poucos, pulsa e fica no Azul JARVIS; usuário: "deu certo" |
| 6 | **Luz acompanha a voz** (novo, pedido do usuário) | REAL-OK (com ressalva) | 1ª versão pouco visível e atrasada; 2ª (azul escuro ↔ ciano, 0,2 s, adiantada 0,15 s): funciona, usuário ainda acha um pouco atrasada — ajuste fica para depois |
| 7 | Desempenho (FPS/CPU/GPU) | NÃO-TESTADO | limite de uso |
| 8 | Núcleo só em 127.0.0.1 | REAL-OK | `netstat`: `127.0.0.1:8765 LISTENING`; pelos 5 IPs da máquina (Wi-Fi 10.0.0.122, Ethernet, VPN…) a conexão é recusada |
| 8 | Acesso de outro aparelho | NÃO-TESTADO | (o bind em loopback já impede) |
| 8 | git status | NÃO-TESTADO | a pasta veio de um .zip, **não é repositório git**; commit não feito |
| 8 | Ponte `led_bridge.py` | REAL-OK | porta 18881 livre (não está rodando) |

## 2. Problemas encontrados e correções

1. **openWakeWord sem modelo** — `scripts/baixar_modelos.py` agora baixa `hey_jarvis_v0.1` + modelos de áudio com
   `openwakeword.utils.download_models`; `app/voice/wake.py` usa a API nova (`wakeword_models`, `inference_framework="onnx"`,
   pois tflite não existe no Windows). `requirements-local.txt` comentário atualizado.
2. **Variáveis vazias no `.env`** (`JARVIS_MODELS_DIR=`) viravam a pasta atual → Piper/Whisper não achados (o núcleo chegou a
   baixar Whisper em `backend/whisper`). `app/config.py`: helper `_env()` trata vazio como ausente. Teste novo.
3. **Whisper local quebrado com PyAV 19** (`open() got an unexpected keyword argument 'metadata_errors'`) — `app/voice/stt.py`
   decodifica o WAV com numpy e entrega float32 ao faster-whisper.
4. **Whisper travava na GPU** (modelo carrega na CUDA, mas falta `cublas64_12.dll`; transcrição falhava ou ficava presa) —
   `auto` só tenta CUDA se cuBLAS/cuDNN carregam; se falhar na GPU, recarrega na CPU uma vez. Teste novo.
5. **Diagnóstico BLE** falhava porque o SAPI (pythoncom) põe a thread em STA — scan agora numa thread própria.
6. **Respostas do roteador gastavam Gemini TTS** — no modo Automático usam voz local (Piper → sistema);
   `app/assistant.py`, `app/voice/tts.py` (`resolve_offline`). Teste novo.
7. **`.env.example` sumiu** da pasta (renomeado para `.env`); restaurado do zip original (chave vazia conferida).
8. `teste_led.py` mostrava "bleak ?" — versão via `importlib.metadata`.

9. **Efeitos de luz** (pedido do usuário): `app/devices/led_effects.py` (novo) + `elk_bleddm.py` (`effect_frame`, `restore`,
   `adopt`, `chosen`), ligados em `assistant.py`; `JARVIS_LED_EFEITOS=voz,inicio|off`. Quadros de efeito nunca esperam fila;
   no fim da fala a fita volta ao estado escolhido; com as luzes desligadas a voz não acende a fita. 7 testes novos.
10. **Rotina parcial dita como "executada"** — `router.py` (`_report`) agora diz "Só em parte" e qual etapa falhou.
11. **"brilho em 30%" ia para a IA** — `router.py` trata "brilho" sem "luz/LED" como luzes (exceto tela/monitor).
12. **IA afirmando ação sem ferramenta** — `assistant.py` (`claims_action`): o HUD recebe o aviso "a IA disse que fez algo,
    mas nenhuma ação foi executada".
13. **Fita fora da tomada: 82 s até falhar** — `elk_bleddm.py`: prazo total de 25 s (`CONNECT_BUDGET_S`) e mensagem clara.
14. **Loop Bluetooth criado na inicialização** (caiu uma vez com WinError 10013) — agora só no 1º uso.

Observado e **não corrigido**:
- Ao iniciar com a fita fora da tomada, o efeito de abertura ocupa a fita por até 25 s; um comando nesse intervalo espera.
- "LEDs em branco" depois do modo cinema mantém o brilho de 15 % (o brilho escolhido persiste entre cores).
- Título da aba do navegador ainda "JARVIS OS 0.2.1"; `package.json` versão 0.2.1.
- Gramática: "Calculadora aberto", "Projeto Projeto JARVIS aberto".
- "Lado a lado" escolhe as duas janelas do topo (incluiu a janela do app Claude).
- Iniciado sem console, o `timeout` do INICIAR.bat falha e o navegador não abre sozinho (duplo clique normal não é afetado).

Arquivos locais alterados (não versionados): `backend/.env` (`JARVIS_LEDS=bluetooth`, `JARVIS_LED_ADDRESS=BE:27:53:00:BC:1B`),
`backend/config/permissions.json` (projeto jarvis → `%USERPROFILE%\Downloads\jarvis-os-0.3\jarvis-hud`; `close_windows: true`).

## 3. Desempenho

Não medido (limite de uso). Whisper small na CPU (int8): ~1,6 s para 3 s de fala, 1ª carga ~4–5 s.
Router: 0,2–3,5 s por comando (o maior foi o primeiro Piper).

## 4. Pendente

Passam para a 0.4: Fase 2 (voz), Fase 3 (microfone real, incluindo se "Jarvis" sem "Hey" dispara), VALIDAR_GEMINI, sem internet,
mídia (Spotify/YouTube), Fase 7 (desempenho), acesso de outro aparelho, ajuste fino do atraso da luz com a voz.
A pasta veio de um .zip e **não é repositório git**: nada foi commitado.
