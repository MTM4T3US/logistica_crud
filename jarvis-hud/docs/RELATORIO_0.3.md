# Relatório — JARVIS OS 0.3 (implementação)

Feito em 12/11/2026, num contêiner Linux na nuvem. **Esta sessão não teve acesso ao seu Windows**,
então nenhuma fase foi executada no seu computador, com o seu microfone, alto-falante, GPU ou fita
de LED. O que roda no Windows foi escrito e testado com dublês; a execução real está no roteiro
[`PROMPT_TESTE_WINDOWS.md`](PROMPT_TESTE_WINDOWS.md), para outra sessão rodar no seu PC.

## Tabela de status

Legenda: **Hardware real** = testado com o equipamento físico · **Só API** = funciona com a API real
do Gemini (testado na 0.2.1) · **Real aqui** = executado de verdade, mas no Linux da nuvem ·
**Dublê** = lógica testada com simulação · **Simulado** = recurso é um simulador · **Pendente**.

| Área | Item | Status |
|---|---|---|
| Fase 1 | `INICIAR.bat`, `VALIDAR_GEMINI.bat`, `DIAGNOSTICO.bat`, `INSTALAR_RECURSOS_LOCAIS.bat` no Windows | **Pendente** (scripts escritos; `diagnostico.py` executado aqui) |
| Fase 1 | Microfone e alto-falante físicos | **Pendente** |
| Fase 1 | CPU, RAM, GPU e FPS no seu PC | **Pendente** (relatório de desempenho implementado no painel) |
| Fase 2 | Amostras da 0.2.1 no painel, com "Usar" | **Real aqui** (tocadas no HUD, núcleo reagindo: nível 0,63) |
| Fase 2 | Gemini TTS em streaming, vozes e estilos | **Só API** (validado na 0.2.1) |
| Fase 2 | Reserva local Piper | **Dublê** (modelo não pôde ser baixado aqui) |
| Fase 3 | Detecção local de "Jarvis" (openWakeWord) | **Real aqui**: fala natural "Jarvis, que horas são?" → 0,996; frases sem a palavra ≤ 0,001 |
| Fase 3 | Transcrição local (faster-whisper) | **Dublê** (modelo não pôde ser baixado aqui) |
| Fase 3 | Nada sai do PC antes da detecção local | **Dublê** (teste automatizado garante que a nuvem não é chamada) |
| Fase 3 | Janela de conversa, interrupção falando, microfone desligado | **Dublê** + HUD no navegador (botões e consentimento verificados) |
| Fase 3 | Eco e ruído reais | **Pendente** |
| Fase 4 | Roteador local (comandos sem Gemini) | **Real aqui** (navegador: "coloque os leds em azul e o volume em 20" → executado sem IA) |
| Fase 4 | Sem internet/sem cota → comandos locais seguem | **Dublê** |
| Fase 4 | Indicadores de conexão, modelo, cota, limite e voz | **Real aqui** (painel STATUS) |
| Fase 4 | Sem testes de modelos a cada inicialização | **Feito** (desligado por padrão; aprende com o uso) |
| Fase 5 | Abrir apps/projetos, volume, mídia, janelas, rotinas | **Dublê** (API do Windows via ctypes, não executada) |
| Fase 5 | Confirmação para fechar janela | **Dublê** |
| Fase 6 | Driver ELK-BLEDDM (bleak) | **Dublê** — bytes, UUID, timeout de 15 s e espera de 0,5 s idênticos aos seus scripts que funcionaram |
| Fase 6 | Ligar, desligar e azul na fita física | **Hardware real, mas com os seus scripts antigos, em outro PC** — o driver do JARVIS ainda não foi visto mudando a fita |
| Fase 6 | Outras cores, brilho, efeitos, fita desconectada | **Pendente** (`TESTAR_LED.bat --completo` testa as cores) |
| Fase 6 | Efeitos de LED sincronizados com a fala | **Não implementado** |
| Fase 5 | "Aberto" só com a janela visível | **Dublê** (o JARVIS espera a janela aparecer por até 6 s antes de afirmar) |
| Fase 7 | Persiana, fechadura, caixinha, robô | **Simulado** + desenho de segurança |
| Fase 8 | Itumbiara, pt-BR, America/Sao_Paulo, clima real | **Real aqui** (Open-Meteo; hoje recusou o IP da nuvem e o HUD mostrou "sem dados") |
| Fase 9 | Chave fora do Git, só localhost, trava de rede | **Real aqui** (testes) |
| Fase 10 | 157 testes do núcleo, build, navegador 14/14 | **Real aqui** |

## O que foi implementado

### Economia do Gemini (Fase 4)
- **Roteador local** (`backend/app/router.py`): entende os comandos do dia a dia em português e
  executa direto, sem Gemini, inclusive compostos ("abra o navegador e coloque os LEDs em roxo").
  Perguntas abertas ("por que…", "explique…") vão para a IA. Opção no painel.
- **Sem cota ou sem internet:** o modo local usa o mesmo roteador, e a voz cai para Piper → voz do sistema.
- **Sem testes na inicialização:** o núcleo aprende com o uso real (modelo que respondeu, cotas
  esgotadas, sobrecarga) e guarda em `backend/data/gemini_state.json`. Modelos que travarem ficam
  20 min de lado.
- **Contagem de cota local** por modelo e dia, mais os limites que o Google informa no erro 429.
  O painel mostra conexão, modelo, pedidos do dia, limites atingidos e provedor de voz.

### Voz (Fase 2)
- As amostras reais da 0.2.1 estão no painel, com as 4 candidatas em destaque. Ouvir não gasta cota;
  "Usar" fixa voz, interpretação e o mesmo modelo de voz da amostra.
- **Piper** (`pt_BR-faber-medium`, masculina) como reserva local, na ordem Gemini → Piper → sistema.

### Escuta local (Fase 3)
- **Detecção de "Jarvis" no computador** (openWakeWord, modelo "hey_jarvis" já incluso no pacote) —
  obrigatória antes de qualquer transcrição na escuta contínua. Sem detector local, a escuta contínua
  fica indisponível (nunca cai para a nuvem).
- **Transcrição local** (faster-whisper), preferida no automático; tenta a GPU e volta para a CPU.
- **Janela de conversa** de 8 s após cada resposta, **interrupção falando** ("Jarvis, pare" — a voz
  abaixa enquanto o PC confere), **microfone desligado** (botão e `Ctrl+M`), **consentimento**
  explícito para a escuta contínua.

### Windows (Fase 5)
- "Aberto" só quando a janela aparece (até 6 s); senão o JARVIS diz que iniciou o programa mas não pode
  confirmar. Resolve o problema antigo da Calculadora "aberta" sem janela.
- Janelas (focar, minimizar, maximizar, metade da tela, lado a lado, mostrar área de trabalho,
  fechar com confirmação), teclas multimídia, volume relativo, projetos cadastrados, rotinas com
  luzes e volume. Tudo restrito ao `permissions.json`; a IA nunca envia comandos de terminal.

### LEDs (Fase 6)
- Seus scripts (`led_test_blue.py`, `led_bridge.py`) confirmaram o protocolo: o driver usa exatamente os
  mesmos bytes, UUID, timeout e espera. Não usa a ponte HTTP: o núcleo fala com a fita direto, numa
  thread de Bluetooth própria (no Windows o bleak não convive com o controle de volume/voz na mesma thread).
- Brilho feito escurecendo a cor (só comandos validados); o comando de brilho da referência pública fica
  opcional (`JARVIS_LED_BRILHO=comando`), marcado como não validado.
- `TESTAR_LED.bat`: teste direto da fita, sem o núcleo, perguntando ao usuário o que ele viu.
- Driver real ELK-BLEDDM (`backend/app/devices/elk_bleddm.py`) com procura por nome, conexão com 3
  tentativas espaçadas, desconexão após 5 min parado (libera o app do celular), estados no painel.
- Honestidade: a fita não confirma comandos. O JARVIS diz "comando enviado" e o painel mostra
  "último comando enviado"; nunca uma animação como prova.

### Segurança (Fase 9)
- O núcleo se recusa a escutar fora do computador sem `JARVIS_ALLOW_LAN=true`, token de 24+ caracteres
  e origem do HUD configurada. Áudio do microfone nunca é gravado em disco. Câmera não é usada.

## Pendências (para a sessão no Windows e para a 0.4)

1. Executar o roteiro `PROMPT_TESTE_WINDOWS.md` e preencher `RELATORIO_WINDOWS_0.3.md`.
2. Ver o driver do JARVIS mudando a fita de verdade (ligar, desligar, azul, demais cores, desconectada).
3. Medir eco e falsos disparos com o seu microfone; calibrar `JARVIS_WAKE_THRESHOLD`.
4. Modelo de palavra-chave treinado para "Jarvis" (sem o "hey"), se o "hey_jarvis" falhar com a sua voz.
5. IA local para assuntos sensíveis (ex.: Ollama no PC), com o Gemini só para assuntos comuns quando
   você escolher — hoje só os comandos são locais; conversa livre usa o Gemini.
6. Efeitos de LED durante a fala (cores em intervalos, respeitando o tempo do Bluetooth, e volta ao estado escolhido).
7. Gemini Live API (conversa contínua nativa), mapa real de Itumbiara, drivers da persiana (ESPHome).
