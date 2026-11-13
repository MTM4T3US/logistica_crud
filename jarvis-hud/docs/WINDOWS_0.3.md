# JARVIS OS 0.3/0.4 no Windows — instalação e uso

## Requisitos

- Windows 10 ou 11, Chrome ou Edge.
- [Python 3.10+](https://www.python.org/downloads/) — marque "Add python.exe to PATH".
- [Node.js LTS](https://nodejs.org).
- Bluetooth (para os LEDs) e microfone/alto-falante (ou fone, que evita eco).
- Opcional: GPU NVIDIA (o HUD usa a GPU pelo navegador; o Whisper pode usar CUDA se as bibliotecas
  da NVIDIA estiverem instaladas — se não, roda na CPU automaticamente).

## Passo a passo

1. **`INICIAR.bat`** — instala o básico, compila o HUD, cria `backend\.env` e
   `backend\config\permissions.json`, inicia o núcleo e abre o navegador.
2. **Chave Gemini** — abra `backend\.env` no Bloco de Notas, cole a chave após `GEMINI_API_KEY=`,
   salve e reinicie o `INICIAR.bat`. Sem chave, tudo que é local continua funcionando.
3. **`INSTALAR_RECURSOS_LOCAIS.bat`** (~1 GB, uma vez) — voz local Piper, transcrição local
   (faster-whisper), detecção local de "Jarvis" (openWakeWord) e Bluetooth (bleak).
4. **`DIAGNOSTICO.bat`** — confere tudo e grava um relatório em `backend\data\`.
   `DIAGNOSTICO.bat --ble` procura as fitas de LED; `--procurar-leds` acha seus scripts antigos.
5. **`backend\config\permissions.json`** — cadastre os programas, pastas, projetos (caminhos reais),
   cenas de luz e rotinas que o JARVIS pode usar. Nada fora dessa lista é executado.
6. **LEDs reais** — feche o LotusLamp X no celular (a fita aceita uma conexão por vez). Teste primeiro com
   **`TESTAR_LED.bat`** (liga, azul, desliga e pergunta o que você viu). Depois, em `backend\.env`:
   `JARVIS_LEDS=bluetooth` e `JARVIS_LED_ADDRESS=` (endereço mostrado pelo diagnóstico; no PC de teste
   era `BE:27:53:00:BC:1B`). A antiga ponte `led_bridge.py` não é necessária — se estiver aberta, feche-a.
7. **`VALIDAR_GEMINI.bat`** (opcional, gasta cota) — testa a IA, gera amostras de voz e mede latência.
8. **0.4 — mapa real:** `cd backend` e `.venv\Scripts\python scripts\baixar_mapa.py` (uma vez; o núcleo
   também baixa sozinho na primeira entrada).
9. **0.4 — entrada:** Configurações → ENTRADA POR ROSTO (PIN + cadastro) e MÚSICA DE ENTRADA (arquivo seu).
   Atualizando da 0.3: descompacte por cima e rode o `INICIAR.bat` — ele instala a biblioteca de rosto
   uma vez. Mantenha `backend\.env`, `backend\config\permissions.json` e `backend\data\`.

## Usar

- **Falar:** botão do microfone (ou `M`).
- **Escuta contínua:** botão do ouvido → Autorizar. Diga "Jarvis, …". A palavra é detectada **no seu
  computador**; só depois o comando é transcrito (localmente, se o Whisper estiver instalado).
  Depois de cada resposta, por 8 s, dá para continuar sem dizer "Jarvis".
- **Interromper:** fale "Jarvis, pare" durante a resposta (a voz abaixa enquanto ele confere), ou
  `Esc`, ou o botão Parar.
- **Microfone desligado:** botão com o microfone riscado, ou `Ctrl+M`.
- **Exemplos de comandos locais (não gastam Gemini):** "coloque os LEDs em azul", "desligue as
  luzes", "ativar modo cinema", "volume 30", "próxima música", "abre o VS Code", "abre o projeto
  jarvis", "organiza as janelas lado a lado", "prepara tudo para programar", "que horas são",
  "como está o clima", "como está meu computador".

## Problemas comuns

| Sintoma | O que fazer |
|---|---|
| Porta 8765 ocupada | `netstat -ano \| findstr 8765` e feche o processo, ou mude `JARVIS_PORT`. |
| "Detecção local de Jarvis indisponível" | Rode `INSTALAR_RECURSOS_LOCAIS.bat`. |
| Whisper lento | Use `JARVIS_WHISPER_MODEL=base`; com GPU NVIDIA e CUDA instalados, `JARVIS_WHISPER_DEVICE=cuda`. |
| Fita não encontrada | Ligue a fita, feche o app do celular, aproxime o PC, rode `DIAGNOSTICO.bat --ble`. |
| Interrupções falsas pelo eco | Use fone, ou desligue "Interromper a resposta" em Configurações → Microfone. |
| Sem voz | Configurações → VOZ → Mecanismo: "Piper" ou "Voz local"; confira o volume do Windows. |
| Câmera bloqueada / "câmera em uso" | Libere no cadeado da barra de endereço; feche outros programas que usam a webcam. Use o PIN. |
| Rosto recusado sendo você | Melhore a luz de frente; cadastre de novo; veja a correspondência (%) e, se preciso, baixe `JARVIS_FACE_THRESHOLD` um pouco. |
| Sem música na entrada | O navegador só toca som depois de um clique: use o botão "Iniciar reconhecimento". |
| Mapa "cidade fictícia" | O mapa real ainda não foi baixado (sem internet?). Rode `scripts\baixar_mapa.py`. |
