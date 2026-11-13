# Prompt para o Claude Code no Windows — testar o JARVIS OS 0.5

> Cole TUDO abaixo da linha em uma sessão do Claude Code (app Claude Desktop ou terminal) aberta
> **no computador Windows**, na pasta onde você descompactou o pacote `jarvis-os-0.5.zip`
> (se a 0.3 já estava instalada: descompacte por cima, mantendo `backend\.env`, `backend\config\permissions.json` e `backend\data\`)
> (ou clonou o branch `ccr-41dc01f1-0wlbjp` do repositório MTM4T3US/logistica_crud — a pasta é `jarvis-hud`).
> Antes de colar: crie `jarvis-hud\backend\.env` a partir de `.env.example` e cole **você mesmo** a
> chave Gemini na linha `GEMINI_API_KEY=` — não cole a chave no chat.

---

Você é o engenheiro de testes do JARVIS OS 0.5 neste computador Windows. O código foi escrito e
testado em Linux na nuvem (testes automatizados, navegador headless com câmera falsa), mas **nada foi
executado neste PC ainda**. Se uma sessão anterior já testou a 0.3 aqui, reaproveite o relatório dela e
foque nas fases novas (12 a 16 na 0.5; 9 a 11 se a 0.4 não foi testada por completo), repetindo só o que a
atualização pode ter afetado. **Antes de tudo:** se a pasta da versão anterior tem correções suas que não
estão neste pacote (veja `docs\RELATORIO_WINDOWS_*.md`), avise o usuário — elas precisam voltar para o
repositório pelo patch (`PROMPT_EXPORTAR_CORRECOES`), não ser refeitas à mão. Sua missão: instalar, executar, testar com o hardware real, corrigir o que for
simples e relatar com honestidade.

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

## FASE 16 — Fechadura

Só se o firmware já estiver pronto (ver `docs\FECHADURA.md`). Caso contrário, anote NÃO-TESTADO.

## Entrega

Crie `jarvis-hud\docs\RELATORIO_WINDOWS_0.5.md` com:

1. Tabela por item: Fase · Teste · Status (REAL-OK / REAL-FALHOU / SÓ-API / SIMULADO / NÃO-TESTADO) · Evidência.
2. Problemas encontrados e correções aplicadas (arquivo e motivo).
3. Desempenho medido (copie os relatórios), incluindo leituras/s do rosto e tempo até entrar.
   Tabela da entrada por rosto: tentativa · pessoa/objeto · correspondência % · anti-foto % · entrou?
4. O que ficou pendente e por quê.

Depois mostre o relatório ao usuário. Se o repositório estiver configurado neste PC, faça um commit
no branch `ccr-41dc01f1-0wlbjp` com o relatório e as correções (sem `.env`, `data`, `models`).
