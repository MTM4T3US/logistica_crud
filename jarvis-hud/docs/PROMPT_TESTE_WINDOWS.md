# Prompt para o Claude Code no Windows — testar o JARVIS OS 0.7

> Cole TUDO abaixo da linha em uma sessão do Claude Code (app Claude Desktop ou terminal) aberta
> **no computador Windows**, na pasta onde você descompactou o pacote `jarvis-os-0.7.0.zip`
> (se a 0.3 já estava instalada: descompacte por cima, mantendo `backend\.env`, `backend\config\permissions.json` e `backend\data\`)
> (ou clonou o branch `ccr-41dc01f1-0wlbjp` do repositório MTM4T3US/logistica_crud — a pasta é `jarvis-hud`).
> Antes de colar: crie `jarvis-hud\backend\.env` a partir de `.env.example` e cole **você mesmo** a
> chave Gemini na linha `GEMINI_API_KEY=` — não cole a chave no chat.

---

Você é o engenheiro de testes do JARVIS OS 0.6 neste computador Windows. O código foi escrito e
testado em Linux na nuvem (testes automatizados, navegador headless com câmera falsa). As versões 0.3 a 0.5.2
já foram testadas neste PC por sessões anteriores: reaproveite os relatórios delas e **foque nas fases novas
(17 a 25)**, depois nas pendências da 0.5.3 (abaixo), repetindo só o que a atualização pode ter afetado.

**Esta versão já inclui TODAS as suas correções** — da 0.3, da 0.4 e do teste da 0.5.2 (os patches
`jarvis-0.4-windows.patch` e `jarvis-0.5.2-windows-teste.patch` foram aplicados; seus relatórios estão em
`docs\RELATORIO_WINDOWS_0.3/0.4/0.5.md`). **Não reaplique patches nem refaça correções à mão.**

Novidades da 0.7 (fases 21 a 25) — confira primeiro:
- **Atualizador:** `ATUALIZAR.bat` (arrastar o zip em cima). **Use-o para instalar esta versão por cima da que já
  está no PC** (fase 21), em vez de descompactar à mão.
- **Celular** na rede de casa (QR), **Telegram** (bot do usuário), **Tailscale** para fora de casa.
- **Assistente:** lista de compras, anotações, dólar/Bitcoin, time, aniversários, resumo da semana.
- **Computador:** Pomodoro com a fita, "lê pra mim", modo jogo automático, gestos com a câmera.
- **Visual:** chuva e noite no mapa, descanso de tela, núcleo que muda de cor.

Novidades da 0.6.1 (fase 20):
- **Entrada só pelo rosto:** não pede mais piscada (opção em Configurações → Entrada); câmera automática opcional.
- **Cidade redesenhada:** ruas de asfalto, casas ilustrativas nas quadras, prédios mapeados com contorno, árvores, rio,
  carros, nomes dos pontos de referência.
- **Qualidade:** antisserrilhado no perfil médio; a qualidade automática não cai mais com a janela escondida.

Novidades da 0.6 (fases 17 a 19):
- **App de verdade:** `INSTALAR_ATALHOS.bat` cria o atalho JARVIS; `JARVIS.bat` abre o núcleo escondido, com
  ícone na bandeja e o HUD numa janela própria; atalhos globais `Ctrl+Alt+J` (abrir) e `Ctrl+Alt+Espaço` (falar);
  "Iniciar com o Windows" (registro do usuário, sem administrador).
- **Cenas da casa:** "bom dia", "modo cinema", "modo foco", "boa noite", "estou saindo", por voz, por botão e por
  horário (Configurações → Casa → CENAS).
- **HUD novo:** barra do topo, coluna CENAS/CASA à direita, histórico (`L`), ajuda (`?`), Configurações em abas,
  lembretes em destaque, tela de bloqueio com relógio.
- "desliga o PC em 10 minutos" agora respeita o tempo (antes ignorava e usava 60 s); acima de 10 minutos ele recusa.

Da 0.5.3 (correções do seu relatório da 0.5.2) — confira se ainda não testou:
- **"seleciona tudo"/"copia" não copiavam: causa encontrada.** As letras dos atalhos iam com o código do teclado
  numérico (0x61/0x63 = Num1/Num3) em vez de 0x41/0x43. Corrigido. Repita na aba EM BRANCO do Bloco de Notas:
  "digita: teste do JARVIS" → "seleciona tudo" → "copia" e confira a área de transferência.
- O título dos compromissos mantém maiúsculas e acentos ("marca Teste do JARVIS amanhã às 9h").
- "academia toda segunda às 8h" (sem "marca") agora é entendido localmente.
- Posts de redes sociais (Instagram, Facebook, TikTok…) não entram mais como manchete. Instale numa pasta NOVA e copie da pasta antiga só:
`backend\.env`, `backend\config\permissions.json`, `backend\data\` e `backend\models\` (não mostre o `.env`).
Depois confira rapidamente que o que você já tinha validado continua igual (LEDs, efeito de entrada, roteador).

## Regras

1. **Nunca afirme que algo funciona sem ter executado e visto o resultado.** Para cada teste,
   registre: comando/ação, o que aconteceu, evidência (saída, número, captura) e status.
2. Status permitidos: **REAL-OK** (funcionou com o hardware real), **REAL-FALHOU**, **SÓ-API**
   (depende só do Gemini e funcionou), **SIMULADO**, **NÃO-TESTADO** (diga o motivo).
3. Peça minha confirmação antes de: instalar programas fora do Python/npm do projeto, mudar
   configurações do Windows, abrir portas no firewall, apagar arquivos, usar a câmera.
4. **Não ative a fechadura**, não destranque nada, não conecte motores. Os LEDs podem ser testados.
5. Não mostre nem copie o conteúdo de `backend\.env` (contém a chave). Nunca faça commit dele.
6. A chave Gemini está no nível gratuito (≈5 pedidos/min e 20/dia **por modelo**). Não gaste cota
   à toa: prefira os testes locais e rode `VALIDAR_GEMINI.bat` **uma** vez.
7. Se corrigir código, rode `cd backend && .venv\Scripts\python -m pytest -q` e `npm run build`
   antes de seguir, e descreva cada correção no relatório.

## Leitura inicial (rápida)

- `jarvis-hud\README.md`, `docs\RELATORIO_0.3.md` (o que foi feito e o que falta),
  `docs\WINDOWS_0.3.md` (instalação), `docs\RELATORIO_0.2.1.md` (validação do Gemini).

## Fatos já comprovados antes desta versão (não refaça a investigação)

- A fita é um controlador **ELK-BLEDDM** (antes usado pelo app LotusLamp X). Em outro PC de teste ela
  anunciava o endereço **`BE:27:53:00:BC:1B`**, característica de escrita
  `0000fff3-0000-1000-8000-00805f9b34fb`.
- O usuário **viu** funcionar, com Python + `bleak`: ligar `7e 04 04 f0 00 01 ff 00 ef`, desligar
  `7e 04 04 00 00 00 ff 00 ef` e azul `7e 00 05 03 00 00 ff 00 ef` (`BleakClient(..., timeout=15)`,
  espera de 0,5 s após conectar, `response=False`). **Nada além disso foi validado** (outras cores,
  brilho, efeitos, leitura de estado).
- Nos testes antigos, outra ferramenta afirmou ter aberto a Calculadora sem que a janela existisse.
  Por isso a 0.3 só diz "aberto" quando **a janela aparece**; confirme isso com os seus próprios olhos.
- O usuário **não** vai usar Home Assistant e quer **uma interface só** (o HUD do JARVIS). A antiga ponte
  HTTP `led_bridge.py` (porta 18881) não é necessária: o núcleo fala com a fita diretamente.
- Este PC (o definitivo) deve ser Windows 10, i7, 16 GB de RAM — confirme.

## FASE 1 — Ambiente e execução

1. Verifique `python --version` (≥ 3.10), `node -v` (≥ 20), `npm -v`, `nvidia-smi`, a versão do Windows,
   CPU e RAM (`systeminfo | findstr /B /C:"Nome do SO" /C:"Versão do SO" /C:"Memória Física Total"`), e se
   há adaptador Bluetooth LE ligado (`Get-PnpDevice -Class Bluetooth` no PowerShell).
2. Dois cliques (ou `cmd /c`) em `INICIAR.bat`. Esperado: instala dependências, compila o HUD, abre
   `http://127.0.0.1:8765` no navegador e o selo do topo mostra "NÚCLEO ONLINE · IA GEMINI".
   Se a porta 8765 estiver ocupada, descubra o processo (`netstat -ano | findstr 8765`) e relate.
3. Rode `INSTALAR_RECURSOS_LOCAIS.bat` (~1 GB: Piper, faster-whisper, openWakeWord, bleak e modelos).
   Relate erros de instalação (ex.: compilação, DLLs) e como resolveu.
4. Rode `DIAGNOSTICO.bat --procurar-leds --ble` e anexe o relatório gerado em `backend\data\`.
5. Reinicie o `INICIAR.bat` e confirme em Configurações → STATUS: conexão, modelo, voz e transcrição.
6. Rode `VALIDAR_GEMINI.bat --rapido` (uma vez) e anexe `backend\samples\validacao.md`.

## FASE 2 — Voz

1. Configurações → VOZ: toque as 4 amostras em destaque (Algieba, Charon, Schedar, Charon sóbria).
   Pergunte ao usuário qual prefere e clique "Usar" nela.
2. Converse por texto: "Jarvis, bom dia" e "Explique em duas frases o que é um buraco negro".
   Meça (Configurações → IA → "Última resposta") os tempos de texto e de voz. O núcleo holográfico
   deve pulsar junto com a voz.
3. Teste a reserva local: em Configurações → VOZ → Mecanismo, escolha "Piper (voz neural local)" e
   faça uma pergunta; depois volte para "Automático". Relate a qualidade percebida pelo usuário.

## FASE 3 — Microfone e alto-falante físicos

1. Botão do microfone: diga "que horas são?". Esperado: transcrição local (Whisper) e resposta falada.
2. Escuta contínua (botão do ouvido → Autorizar): diga "Jarvis, abre a calculadora". Depois, sem
   dizer "Jarvis", em até 8 s: "e fecha o bloco de notas" (deve pedir confirmação para fechar).
3. Fale uma frase SEM "Jarvis" (ex.: conversa com outra pessoa): deve ser ignorada. Confirme no log
   do núcleo que nada foi enviado à nuvem.
4. Interrupção: peça uma explicação longa e, enquanto ele fala, diga "Jarvis, pare". Esperado: a voz
   abaixa, ele para. Relate se o eco da própria voz dispara interrupções falsas (com e sem fone).
5. Botão de microfone desligado (ou Ctrl+M): confirme que nada é captado.
6. Ruído: teste com música/ventilador ligados e relate falsos disparos.

## FASE 4 — Economia do Gemini

1. Comandos que NÃO devem gastar Gemini (o fim do turno mostra modo "router"): "volume 30",
   "próxima música", "abre o VS Code", "coloque os leds em azul", "que horas são", "como está o clima".
2. Simule ficar sem internet (desative o Wi-Fi por 1 min **com autorização do usuário**): os comandos
   acima devem continuar funcionando e a voz deve cair para Piper. Religue a internet.
3. Confira em Configurações → STATUS a contagem de pedidos do dia por modelo.

## FASE 5 — Controle do Windows

Para cada "abrir", o JARVIS só deve dizer "aberto" se a janela apareceu; caso contrário, diz que não
pode confirmar. **Confira na tela** (ou com uma captura) se a janela existe mesmo, e registre se a
mensagem do JARVIS bateu com a realidade. Teste e relate cada um: abrir VS Code/navegador/calculadora; "abre o projeto jarvis" (ajuste antes
`backend\config\permissions.json` com os caminhos reais dos projetos do usuário); "volume 20",
"aumenta o volume", "mudo"; "pausa a música"/"próxima música" com o Spotify ou YouTube tocando;
"organiza as janelas lado a lado"; "minimiza o navegador"; "maximiza o código"; "prepara tudo para
programar" (deve pedir confirmação); "fecha o bloco de notas" (habilite antes
`"close_windows": true` em `permissions.json` e confirme que pede confirmação específica).
Para cada falha, relate a mensagem exibida.

## FASE 6 — LEDs ELK-BLEDDM

1. Se o usuário tiver os scripts antigos (`led_test_blue.py`, `led_bridge.py`, `led_inspect.py`) neste PC,
   `DIAGNOSTICO.bat --procurar-leds` os encontra. Os bytes e o UUID devem ser os mesmos do driver
   `backend\app\devices\elk_bleddm.py`; se forem diferentes, **adapte o driver** e explique.
2. Peça ao usuário para ligar a fita e **fechar/desconectar o LotusLamp X** no celular (a fita aceita uma
   conexão por vez). Rode `DIAGNOSTICO.bat --ble` e confirme o endereço (era `BE:27:53:00:BC:1B` no PC de teste).
3. **Teste direto, sem o núcleo:** `TESTAR_LED.bat --endereco <endereço>` envia ligar → azul → desligar e
   pergunta, a cada passo, se a fita mudou. Repasse cada pergunta ao usuário no chat e digite a resposta
   dele. Depois `TESTAR_LED.bat --endereco <endereço> --completo --inspecionar` (vermelho, verde, branco,
   branco a 30 %). Anexe os relatórios `backend\data\teste-led-*.md`.
4. Só então, no JARVIS: em `backend\.env`, `JARVIS_LEDS=bluetooth` e `JARVIS_LED_ADDRESS=<endereço>`.
   Reinicie. Configurações → DISPOSITIVOS → Conectar. Diga/digite: "coloque os LEDs em azul",
   "desligue as luzes", "LEDs em vermelho", "ativar modo cinema", "brilho em 30%".
5. **Confirme com o usuário, olhando a fita**, se cada comando mudou a luz. O painel só mostra "comando
   enviado" — a fita não confirma. Registre REAL-OK somente com a confirmação visual do usuário.
   O brilho é feito escurecendo a cor (só usa o comando de cor). O comando de brilho próprio da fita
   (`JARVIS_LED_BRILHO=comando`) não é validado: teste-o só se o usuário quiser, e relate.
6. Teste a fita **desconectada**: tire-a da tomada, dê um comando (deve falhar em até ~25 s com mensagem
   clara, sem travar o HUD), religue e dê outro comando (deve reconectar sozinho).
7. Teste com o volume e a voz em uso (o Bluetooth roda numa thread própria justamente para não conflitar
   com o controle de volume e a voz do Windows): "volume 30" e logo depois "LEDs em azul".
8. Não implemente efeitos de LED sincronizados com a fala nesta etapa; registre como pendente.

## FASE 7 — Desempenho

1. Com o HUD em tela cheia (F), qualidade "Média", em repouso: Configurações → DESEMPENHO → "Medir 30 s".
2. Repita falando (durante uma resposta longa) e com qualidade "Alta".
3. Anexe os relatórios gerados em `backend\data\desempenho-*.md` (FPS, CPU, RAM, GPU via nvidia-smi).

## FASE 8 — Segurança

1. Confirme que o núcleo escuta só em 127.0.0.1: `netstat -ano | findstr 8765`.
2. Abra `http://<IP-da-rede>:8765` de outro aparelho: deve falhar.
3. Confirme que `backend\.env`, `backend\data\` e `backend\models\` não aparecem em `git status`.
4. Se a ponte antiga `led_bridge.py` estiver rodando, avise o usuário: ela não é mais necessária e
   ocupa a fita (uma conexão por vez). Não a encerre sem perguntar.

## FASE 9 — Entrada por rosto (0.4)

**Peça autorização ao usuário antes de ligar a câmera.** Nada é gravado: só números (descritores) vão
para `backend\data\rosto.json`. Não fotografe o usuário nem salve quadros da câmera.

1. Configurações → ENTRADA POR ROSTO: o usuário digita um PIN reserva e clica "Cadastrar meu rosto".
   Ele pisca uma vez e vira o rosto de leve (6 capturas). Anote o tempo total e as "LEITURAS/S NESTE PC"
   mostradas no painel da direita. Confirme que o holograma do rosto acompanha o rosto real dele.
2. "Bloquear agora" → tela "IDENTIFICAÇÃO NECESSÁRIA" → "Iniciar reconhecimento". Ele olha e pisca.
   Meça o tempo até entrar e anote a CORRESPONDÊNCIA (%) mostrada. Repita 5 vezes (luz normal, luz fraca,
   de óculos/boné se ele usar) e anote cada valor.
3. Recusas esperadas (anote a correspondência de cada uma):
   - uma foto do usuário no celular, parada (não pode entrar: não pisca);
   - **com o consentimento dela**, outra pessoa da casa olhando e piscando (não pode entrar);
   - um vídeo do usuário piscando no celular — **limitação conhecida**: pode entrar; relate o que acontecer.
4. Com os números, sugira o `JARVIS_FACE_THRESHOLD` (padrão 0,62): acima dos valores de outras pessoas e
   abaixo dos do usuário. Não mude sem mostrar os números a ele. Anote também ANTI-FOTO e VIDA (%): se
   separarem bem foto de rosto real, proponha `JARVIS_FACE_ANTISPOOF_MIN`.
5. PIN reserva: entre com o PIN; erre 5 vezes e confirme a pausa de 30 s.
6. Feche o navegador por mais de 2 min e abra de novo: deve pedir o rosto. Recarregar (F5) não deve pedir.
7. Confirme que a luz da webcam APAGA depois da entrada.

## FASE 10 — Música e sequência de entrada

1. O usuário escolhe, em Configurações → MÚSICA DE ENTRADA, um arquivo de música **dele** (ex.: a faixa que
   ele comprou/baixou legalmente). Não baixe música da internet.
2. "Testar a entrada agora": a música começa, depois de ~5 s o JARVIS dá as boas-vindas, voa para a cidade
   e fala clima e notícias; a música abaixa enquanto ele fala e some no fim. Relate o volume, o momento da
   fala e se o corte ficou bom. Ajuste os controles (volume, atraso da voz) com o usuário.
3. Faça a entrada completa: bloquear → rosto → música → boas-vindas → cidade.

## FASE 11 — Mapa real e resumo

1. `cd backend` e `.venv\Scripts\python scripts\baixar_mapa.py`: anote ruas/prédios/rio baixados.
2. "Jarvis, mostra o mapa": a nota no rodapé deve dizer MAPA REAL · OPENSTREETMAP. Pergunte ao usuário se
   ele reconhece as ruas de Itumbiara (avenidas, rio Paranaíba). Capture a tela.
3. "Quais as novidades": clima real e manchetes reais (confira 2 links). Nada pode ser inventado.
4. "Bloqueia o Jarvis": deve bloquear; nenhum comando de voz desbloqueia.

## FASE 12 — Controle amplo do computador (0.5)

Peça autorização ao usuário antes de cada bloco. Para cada comando, confira **na tela** se aconteceu o que
o JARVIS disse:
1. "abre o Word", "abre o Spotify", "abre a calculadora", "abre o WhatsApp": deve dizer "aberto" só se a
   janela apareceu.
2. "abre o site youtube.com", "pesquisa receita de pão de queijo no youtube", "abre as configurações de
   bluetooth".
3. "procura o arquivo <algo que exista>" → "abre o 1" → "mostra o 1 na pasta". Crie um arquivo de teste
   para "manda o 1 para a lixeira" (deve pedir confirmação). Confira na Lixeira.
4. "tira um print" (Imagens\JARVIS), "brilho da tela em 60" (notebook).
5. Abra o Bloco de Notas: "digita: teste do JARVIS", "seleciona tudo", "copia".
   Abra o PowerShell e tente "digita: dir": **deve recusar**.
6. "fecha o bloco de notas" (confirmação), "bloqueia o computador" (o usuário desbloqueia).
7. "desliga o computador" → confirme → **imediatamente** "cancela o desligamento". Não deixe desligar.

## FASE 13 — Computer use (gasta cota: no máximo 2 tarefas)

1. "Jarvis, usa o computador para abrir a calculadora e calcular 12 vezes 8": acompanhe e anote passos,
   tempo e se acertou os cliques.
2. Durante uma tarefa, mexa o mouse: deve parar e dizer por quê.
3. Peça algo que envolva "enviar" (ex.: rascunho de e-mail sem destinatário real): deve pedir confirmação.
   Negue.
4. Relate a precisão dos cliques (escala do Windows 100/125/150 %).

## FASE 14 — Agenda

1. "marca dentista amanhã às 15h", "academia toda segunda às 8h", "o que eu tenho amanhã?", "desmarca o
   dentista" (confirmação).
2. Marque algo para daqui a 17 minutos e confira o lembrete falado (15 min antes).
3. Bloqueie e entre de novo: as boas-vindas devem dizer os compromissos de hoje.

## FASE 15 — Luzes Smart Life / Tuya

1. `CONFIGURAR_LUZES.bat` com o usuário (ele cria a conta em iot.tuya.com e vincula o app). Nunca mostre as
   chaves nem copie `devices.json` ou `tinytuya.json`.
2. `CONFIGURAR_LUZES.bat --testar`: confirme com o usuário, olhando, que cada luz piscou.
3. No JARVIS: "apaga as luzes", "acende a luz da sala", "luz do quarto em azul", "luzes a 30%". O JARVIS
   diz "confirmado pelos aparelhos"; confirme olhando. Tire uma lâmpada da tomada e veja a mensagem.

## FASE 16 — Fechadura do TCC (ESP32 + solenoide 12 V)

Leia `docs\FECHADURA.md` antes. **Regras extras:**
- **Faça uma cópia da pasta do firmware** antes de mexer em qualquer coisa.
- **Antes de gravar no ESP32,** mostre o diff ao usuário e peça autorização.
- **Nunca implemente** uma rota de destrancar pela rede.
- **Não acione a abertura da fechadura pelo painel do Render nem pelo app.**

1. **Encontrar o firmware:** pergunte ao usuário onde está a pasta do firmware (o `.ino` ou o
   `src/main.cpp`) e com o que ele grava (Arduino IDE ou PlatformIO). Leia como o código abre a porta
   hoje: teclado, comandos do app/backend, rosto.
2. **Copiar o módulo:** coloque `firmware\fechadura_jarvis\JarvisLock.h` e `jarvis_proto.h` na pasta do
   sketch e crie `secrets.h` a partir de `secrets.example.h`.
3. **Encaixar no código dele,** como em `exemplo_integracao.ino`:
   - `begin` no `setup` e `loop` no `loop`;
   - no ponto que abre a porta: recusar app/rosto/painel com `lockdown()` ligado e registrar com
     `logEvent(origem, true)`;
   - `logEvent("teclado", false)` em código errado;
   - `setLockdown(false)` atrás do código mestre.

   Se o código usa `delay()` na abertura, troque pelo temporizador do exemplo. Explique cada mudança.
4. **Conectar à rede:** coloque o ESP32 no Wi-Fi de casa, com IP fixo no roteador (pergunte ao usuário), e
   rode `backend\.venv\Scripts\python backend\scripts\parear_fechadura.py http://IP:8080`. O segredo vai
   para o `secrets.h`; não mostre o segredo em relatórios.
5. **Compilar e gravar:** compile primeiro e corrija só erros de compilação. Grave somente com a
   autorização do usuário.
6. **Testar com a fechadura,** confirmando com o usuário, olhando:
   - "a porta está trancada?";
   - abrir pelo teclado: o JARVIS deve ver o evento;
   - "tranca a porta" durante uma abertura;
   - "ativa o modo trancado": o app e o rosto **não** abrem, o teclado abre; depois desligue com o código mestre;
   - 3 códigos errados: alerta;
   - "destranca a porta": recusa.
7. **Confirmar o que continua igual:** o app do TCC e o painel seguem funcionando fora do modo trancado.

## FASE 17 — App do Windows (0.6)

1. Rode `INICIAR.bat` uma vez (instala `pystray` e `pillow`, novas dependências) e feche.
2. `INSTALAR_ATALHOS.bat`: confira o atalho **JARVIS** na Área de Trabalho e no Menu Iniciar. Responda **N** à
   pergunta de iniciar com o Windows por enquanto.
3. Abra pelo atalho. Confira e registre:
   - sem janela de console;
   - ícone na bandeja;
   - o HUD numa janela própria, sem barra de endereço, com o título "JARVIS OS";
   - `backend\data\jarvis.log` sendo escrito.
4. Clique duas vezes no atalho de novo: **não** pode subir um segundo núcleo (a janela existente vem para a
   frente). Verifique no Gerenciador de Tarefas: só um `pythonw`.
5. Atalhos globais, com outro programa em foco (ex.: Bloco de Notas):
   - `Ctrl+Alt+J` traz o HUD;
   - `Ctrl+Alt+Espaço` começa a gravar (o HUD mostra MICROFONE CAPTURANDO).

   Se algum atalho já for usado por outro programa, o log diz qual; troque em `backend\.env`
   (`JARVIS_HOTKEY_OPEN` / `JARVIS_HOTKEY_TALK`) e repita.
6. Menu da bandeja: Abrir, Falar, Bloquear o JARVIS (com rosto cadastrado), Abrir a pasta de dados, Ver o
   registro, Sair. **Sair** encerra tudo: nenhum `pythonw` sobrando e a porta 8765 livre.
7. **Iniciar com o Windows**, pelo menu da bandeja **e** por Configurações → Sistema:
   - ligar e conferir em `HKCU\Software\Microsoft\Windows\CurrentVersion\Run` o valor "JARVIS" (só leitura,
     com `reg query`);
   - desligar e conferir que o valor sumiu.

   **Só reinicie o PC para testar se o usuário autorizar.** Ao iniciar, deve aparecer só o ícone, sem abrir o HUD.
8. Navegador: o app usa Edge, Chrome ou Brave, nessa ordem, com um perfil próprio em `%LOCALAPPDATA%\JARVIS\navegador`.
   Confira que a música de entrada toca sem precisar clicar antes.

## FASE 18 — Cenas da casa (0.6)

Para cada cena, por voz ou texto **e** pelo botão em CENAS:
1. "modo cinema": casa apagada (se houver Tuya), fita em modo cinema, volume 35. Confira a resposta: se ele pulou
   uma etapa por falta de recurso, deve dizer quantas.
2. "modo foco" e "boa noite": confira cada etapa real; "boa noite" tranca a porta só se a fechadura estiver
   pareada (senão: simulador).
3. "bom dia" (sozinho): faz a cena e fala o resumo. "bom dia, que horas são?": **só** diz a hora, sem a cena.
4. "estou saindo": pede confirmação; recuse uma vez (nada acontece) e aceite outra.
   **Ela bloqueia o Windows**: avise o usuário antes.
5. Horário: em Configurações → Casa → CENAS, agende "modo foco" para daqui a 2 minutos. Espere com o JARVIS
   aberto e confira:
   - roda uma vez;
   - aparece um aviso em destaque no topo;
   - entra no histórico (`L`).

   Depois desligue o agendamento.
6. Agende "estou saindo" para daqui a 2 minutos: no horário ele só deve **avisar** (não executar).
   Depois desligue o agendamento.
7. Bloqueado (com rosto cadastrado): agende "bom dia". No horário, ele deve fazer a cena e só cumprimentar, sem
   falar clima, notícias nem agenda.
8. Botões CASA: Acender/Apagar (com Tuya: casa + fita; sem Tuya: só a fita), "Porta?", Trancar. **Não use
   "Trancado" (modo trancado) sem o usuário por perto e de acordo.**

## FASE 19 — HUD novo (0.6)

1. Capturas em 1920×1080 e numa janela menor (~1000 px de largura) em repouso. Confira:
   - nada cortado na borda esquerda;
   - coluna CENAS/CASA legível;
   - a barra de comando não fica esmagada.
2. `L` abre o histórico com a conversa e os avisos (horário de Itumbiara); `?` abre a ajuda; `Esc` fecha os dois.
3. Configurações: percorra as 6 abas. Confira que a escuta contínua, o cadastro de rosto, a agenda e as vozes
   continuam funcionando nas novas abas.
4. Tela de bloqueio: relógio e data de Itumbiara; entrar pelo rosto e pelo PIN.
5. Meça o FPS em repouso (Configurações → Sistema → Medir 30 s) e compare com a 0.5. A coluna nova não deve
   derrubar o FPS.

## FASE 20 — 0.6.1: rosto, cidade e qualidade

1. **Entrada só pelo rosto** (com o usuário na frente da câmera):
   - entrar **sem piscar**, cinco vezes; anote correspondência e tempo até entrar;
   - outra pessoa da casa, se o usuário quiser, sem piscar: **não pode** entrar;
   - **uma foto do usuário no celular**, mostrada para a câmera: anote se entra (esperado: pode entrar, por isso
     existe a opção da piscada). Conte isso ao usuário;
   - ligue "Ligar a câmera sozinho" e bloqueie: a câmera deve ligar sem clique;
   - desmarque "Entrar só pelo rosto": deve voltar a pedir a piscada. Deixe como o usuário preferir.
2. **Cidade real:**
   - "mostra o mapa", com a Itumbiara baixada (se não estiver: `backend\.venv\Scripts\python
     backend\scripts\baixar_mapa.py`);
   - capturas em 1920×1080 aos ~10 s e ~25 s;
   - pergunte ao usuário se reconhece o centro, o rio e as avenidas;
   - confira se há casas em cima de rua ou dentro do rio (não deveria);
   - no console do HUD (F12), leia `__city` (tempo de montagem e quantidades).
3. **Qualidade:**
   - Configurações → Sistema: qualidade em "Automática". Use 2 min com o HUD em primeiro plano e confira se continua
     "medium";
   - esconda a janela por 1 min e volte: **não** deve ter caído para "low";
   - meça o FPS em 1080p no repouso e no mapa (Medir 30 s), em "Média" e em "Alta";
   - recomende a melhor para a RTX 2050.

## FASE 21 — Atualizador (0.7)

1. A pasta instalada ainda não tem o atualizador (ele é novo). Só desta vez, copie do zip para a pasta instalada:
   - `jarvis-hud\ATUALIZAR.bat`;
   - `jarvis-hud\backend\scripts\atualizar.py`.

   Depois, com o JARVIS fechado, arraste `jarvis-os-0.7.0.zip` em cima do `ATUALIZAR.bat`. Anote:
   - versão antes e depois;
   - quantos arquivos trocou;
   - onde ficou o backup (`backend\data\atualizacoes\`).
2. Confira que continuam iguais:
   - a `backend\.env` (só confira que a chave ainda está lá, **sem mostrar**);
   - o `permissions.json`;
   - o rosto cadastrado;
   - a agenda;
   - o mapa.
3. Com o JARVIS aberto, rode de novo: ele deve recusar ("Feche-o antes").
4. Teste `ATUALIZAR.bat --voltar` e depois atualize de novo para a 0.7.

## FASE 22 — Celular e Tailscale (0.7)

1. Configurações → Sistema → CELULAR → ligar. Quando o Windows perguntar sobre a rede, permita **só em redes
   privadas** (com o usuário). Anote o endereço mostrado.
2. "Parear celular": o usuário lê o QR com o celular (mesmo Wi-Fi). Teste no celular:
   - uma cena;
   - "Saindo" (deve pedir confirmação);
   - Acender e Apagar;
   - "Porta?";
   - pôr e tirar item da lista;
   - anotar;
   - conversa por texto ("que horas são");
   - resposta "falada no PC" e "com voz no celular".
3. Pelo celular, peça "digita oi" e "tira um print": devem ser **recusados** ("só no próprio computador").
4. Remova o aparelho no HUD e confira que o celular perde o acesso (volta para a tela de pareamento).
5. Se o usuário quiser: Tailscale no PC e no celular, e o mesmo teste com o celular **fora** do Wi-Fi (4G), pelo
   endereço 100.x. **Nunca** abra portas no roteador.

## FASE 23 — Telegram (0.7)

1. Guie o usuário pelo @BotFather (`docs\TAILSCALE_E_TELEGRAM.md`). **Ele mesmo** cola o token no `.env`; não
   mostre nem copie o token.
2. Reinicie o JARVIS → Sistema → TELEGRAM → Gerar código → `/parear CÓDIGO` no bot.
3. Teste:
   - "modo foco";
   - `/cenas` e um botão;
   - "limpa a lista" (botões Sim/Não);
   - "a porta está trancada?";
   - "quanto está o dólar?";
   - `/semana`.
4. Avisos: marque um compromisso para daqui a 16 minutos e confira o lembrete no Telegram. Com a fechadura pareada,
   uma abertura pelo teclado deve gerar aviso.
5. Com outra conta do Telegram (se houver), mande uma mensagem ao bot: **não** pode responder.

## FASE 24 — Computador e assistente (0.7)

1. "põe leite, pão e café na lista", "tira o pão da lista", "o que tem na lista?". Depois "anota: teste do JARVIS",
   "minhas anotações".
2. "começa um pomodoro de 2 minutos com pausa de 1": a fita fica branca e depois verde, com aviso falado e o tempo no
   topo. "para o pomodoro".
3. "Lê pra mim":
   - selecione um parágrafo no Bloco de Notas e diga "lê pra mim": deve ler, e a área de transferência deve voltar ao que era;
   - num terminal: deve recusar.
4. **Modo jogo:**
   - abra um jogo da Steam/Epic/Riot (se houver): o HUD deve pausar (GPU do navegador cai no Gerenciador de Tarefas)
     e voltar ao sair do jogo;
   - teste também "modo jogo" / "sai do modo jogo".
5. **Gestos** (com o usuário, câmera): ligue em Sistema → COMPUTADOR. Teste cada gesto:
   - ✋ com uma música tocando;
   - 👍 e 👎 para o volume;
   - ✌ para a próxima faixa.

   Anote quantas tentativas cada um precisou. Desligue: a luz da câmera deve apagar.
6. **Boletim:**
   - em Geral → BOLETIM, ponha o time do usuário;
   - teste "quanto está o dólar?" e "e o meu time?";
   - teste a entrada (boas-vindas com o dólar).

## FASE 25 — Visual (0.7)

1. "mostra o mapa" à noite (ou de dia, anotando): janelas acesas e céu escuro à noite. Se chover em Itumbiara no
   dia, confira a chuva.
2. Descanso de tela: Sistema → COMPUTADOR → 2 minutos; fique 2 min parado; deve aparecer o relógio grande e
   sumir ao mexer o mouse.
3. Núcleo: um comando que funciona (pulso verde), um que pede confirmação (âmbar enquanto espera) e um que falha
   (avermelhado).
4. FPS no repouso e no mapa (Medir 30 s), comparando com a 0.6.1.

## Entrega

Crie `jarvis-hud\docs\RELATORIO_WINDOWS_0.7.md` com:

1. Tabela por item: Fase · Teste · Status (REAL-OK / REAL-FALHOU / SÓ-API / SIMULADO / NÃO-TESTADO) · Evidência.
2. Problemas encontrados e correções aplicadas (arquivo e motivo).
3. Desempenho medido (copie os relatórios), incluindo leituras/s do rosto e tempo até entrar.
   Tabela da entrada por rosto: tentativa · pessoa/objeto · correspondência % · anti-foto % · entrou?
4. O que ficou pendente e por quê.

Depois mostre o relatório ao usuário. Se o repositório estiver configurado neste PC, faça um commit
no branch `ccr-41dc01f1-0wlbjp` com o relatório e as correções (sem `.env`, `data`, `models`).
