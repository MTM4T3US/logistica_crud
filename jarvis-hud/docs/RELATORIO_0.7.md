# Relatório — JARVIS OS 0.7 (celular, Telegram, assistente, computador e visual)

Feito em 13/11/2026, num contêiner Linux na nuvem, **sem Windows, sem celular de verdade e sem acesso ao Telegram**.
O que depende deles foi testado com dublês:
- **celular:** navegador em tamanho de iPhone;
- **Telegram:** um servidor falso da API;
- **teclado e área de transferência:** dublês.

O teste real fica para o chat do Windows ([`PROMPT_TESTE_WINDOWS.md`](PROMPT_TESTE_WINDOWS.md), fases 21 a 25).

Pedido: "gostei de todas as ideias, pode implementar todas. O casa fica pra depois se eu comprar os sensores".

## O que foi feito

### Celular e fora de casa

| Ideia | Feito |
|---|---|
| JARVIS no celular | **O que mostra:** página própria para o celular (instalável na tela inicial) com conversa por texto, cenas, casa, porta, agenda, lista de compras, anotações e Pomodoro. A resposta pode vir por escrito, falada no celular ou no PC. Para falar, o microfone do teclado (ditado). **Como liga:** é um servidor **separado** (porta 8766) que só sobe quando você liga em Configurações → Sistema → CELULAR. **Pareamento:** QR ou código de 6 dígitos (5 minutos, 5 tentativas); cada aparelho recebe uma chave só dele, e o PC guarda só o hash; dá para remover no HUD. |
| Telegram | **Pareamento:** bot seu (token no `.env`), pareado com **um** chat por código; outras pessoas e grupos são ignorados em silêncio. **Uso:** comandos como no HUD, atalhos `/cenas` `/lista` `/porta` `/semana`, confirmações com botões Sim/Não. **Avisos:** agenda, fechadura, cenas agendadas, fim do Pomodoro e resumo da semana. O PC só faz pedidos para fora. |
| Fora de casa | Pelo **Tailscale** (guia em [`TAILSCALE_E_TELEGRAM.md`](TAILSCALE_E_TELEGRAM.md)). Nunca por portas abertas no roteador. |
| Atualizador | `ATUALIZAR.bat`: **arraste o zip novo em cima dele** (ou ele faz `git pull`, se for um clone). **O que fica:** `.env`, `permissions.json`, `backend\data` (rosto, agenda, listas, mapa, aparelhos, Telegram) e os modelos. **Antes de trocar:** guarda a versão atual para `ATUALIZAR.bat --voltar`. Recusa zip que não é do JARVIS e caminhos suspeitos, e não roda com o JARVIS aberto. |

**O que nunca roda de fora do PC** (celular e Telegram), em nenhum caminho:
- computer use, digitar e atalhos de teclado;
- captura de tela e ler a seleção;
- Lixeira e encerrar processos;
- destrancar a porta (não existe em lugar nenhum).

O resto passa pelas mesmas ferramentas, confirmações e registros do HUD, e aparece no HUD ("📱 Celular: …").

### Computador

| Ideia | Feito |
|---|---|
| Gestos com a webcam | **Gestos:** ✋ mão aberta = tocar/pausar · 👍 👎 = volume · ✌ = próxima faixa. O gesto precisa ficar parado ~0,6 s; depois há uma pausa para não repetir. **Privacidade:** desligado por padrão; com ele ligado, a câmera fica ligada e o HUD mostra "● CÂMERA: GESTOS"; pausa com o JARVIS bloqueado ou em modo jogo. Tudo no PC. |
| Modo jogo | **Automático:** com um jogo em primeiro plano (pastas da Steam, Epic, Riot, Xbox, EA, Ubisoft, GOG, Battle.net, Rockstar ou a sua lista em `"jogos"`), o HUD **para de desenhar** (libera a placa de vídeo) e a fita vai para a cor de jogo (opcional). Sai sozinho quando o jogo sai da frente (2 leituras, para não piscar no Alt+Tab). Também por voz e pelo botão "Voltar ao HUD". |
| Pomodoro com a fita | "começa um pomodoro (de 50 minutos com pausa de 10)", "quanto falta?", "para o pomodoro". Fita branca no foco, verde na pausa, azul na pausa longa. Avisa a cada troca; o tempo aparece no topo do HUD. |
| "Lê pra mim" | Lê o texto **selecionado** na janela em foco: copia, lê e devolve o que estava na área de transferência. Recusa terminais (lá o Ctrl+C interrompe programas) e janelas de senhas. |
| "Anota isso" | "anota: ligar para o banco", "minhas anotações (da semana)", "apaga a anotação do banco" (pede confirmação). Com data e hora vira compromisso da agenda, como antes. |

### Assistente

| Ideia | Feito |
|---|---|
| Boletim maior | **Nas boas-vindas:** dólar (e Bitcoin, opcional) pela AwesomeAPI, manchetes do seu time pelo Google Notícias e os aniversários de hoje. Com a fonte; sem resposta dela, ele diz que não conseguiu. **Por voz:** "quanto está o dólar?", "e o Goiás?". |
| Lista de compras | "põe leite, pão e café na lista", "tira o pão da lista" (acha sem acento e por parte do nome), "o que tem na lista?", "limpa a lista" (pede confirmação). No HUD, no celular e no Telegram. |
| Resumo da semana | **Conteúdo:** domingo às 20h (ajustável), os compromissos dos próximos 7 dias, os aniversários, a previsão (máximas, mínimas, dias de chuva) e as pendências (lista e anotações). **Onde:** falado no HUD e enviado ao Telegram. Com o JARVIS bloqueado, a tela só avisa que está pronto. |

### Visual

| Ideia | Feito |
|---|---|
| Clima de verdade no mapa | **Chuva:** cai sobre a cidade quando está chovendo em Itumbiara (Open-Meteo). **À noite** (pelo dia/noite real): céu escuro, janelas acesas (cada casa com umas acesas e outras não), luzes de rua e faróis mais fortes. |
| Descanso de tela | Depois de X minutos parado (padrão 10; dá para desligar), o HUD some e fica um relógio grande ao lado do núcleo, com a data, o clima e o próximo compromisso. Qualquer movimento volta. Não entra com fala, painel aberto ou confirmação pendente. |
| Núcleo com humor | Pulso **verde** quando algo é feito, **âmbar** enquanto espera um "sim" ou num aviso, **vermelho-alaranjado** em falha. |

### Correções no caminho

- **"Saindo de casa" e o modo trancado:** com a fechadura simulada, a cena dizia "falhou: ação lockdown não existe". Agora a etapa é pulada como recurso ausente, e o botão "Modo trancado" só aparece com a fechadura real.
- **Contagem de etapas:** a confirmação conta só as etapas que vão rodar ("(1 etapa)").
- **Item repetido na lista:** pôr um item que já estava na lista não aparece mais como falha.

## Testes executados aqui

- **Núcleo:** 368 testes (319 → 368).
  - **Lista e anotações:** separação dos itens, sem acento, privacidade com o JARVIS bloqueado.
  - **Cotações:** fonte real e fonte fora do ar.
  - **Pomodoro:** ciclos com relógio falso.
  - **Jogos:** reconhecimento e liga/desliga com folga.
  - **Ler a seleção:** devolve a área de transferência; recusa terminal.
  - **Resumo da semana:** conteúdo, só no domingo e uma vez.
  - **Boletim:** cotação e aniversário nas boas-vindas.
  - **Roteador:** 21 frases novas, todas sem Gemini.
  - **Celular:** código vence, 5 tentativas, só o hash no disco, sem chave = 401, cenas com a mesma confirmação, ações de tela bloqueadas. Servidor do celular **subindo e descendo de verdade** numa porta própria, sem a API do HUD exposta.
  - **Telegram (servidor falso):** pareamento, outro chat e grupo ignorados, botão apertado por outro chat ignorado, confirmação por botão, avisos, token recusado.
  - **Atualizador:** mantém `.env`, permissões e rosto; volta atrás; recusa zip estranho e caminhos para fora.
- **Atualizador no pacote real:** aplicado sobre uma cópia do pacote 0.6.1, manteve a `.env` e o rosto e trouxe os arquivos novos.
- **Navegador:** 21 de 21 verificações (18 + seções novas, lista por voz, Pomodoro no topo).
- **Celular** (tamanho de iPhone 13): pareamento pelo link do QR, conversa, cena com confirmação; sem erros.
- **Gestos:**
  - a classificação (mão aberta, polegar para cima e para baixo, V, apontar) e a trava contra repetição foram testadas à parte;
  - no navegador, com câmera falsa: os modelos de mão carregam, o indicador aparece e some ao desligar;
  - **com uma mão de verdade: pendente** no seu PC.

## Status

| Item | Status |
|---|---|
| Lista, anotações, Pomodoro, boletim, resumo da semana | **Real aqui** (núcleo + HUD); cotações e notícias do time dependem da internet do PC |
| Celular | **Real aqui** num celular emulado — pendente com o seu celular, o Wi-Fi e o firewall do Windows |
| Telegram | **Dublê** (API falsa) — pendente com o seu bot |
| Modo jogo, "lê pra mim" | **Dublê** — pendentes no Windows com um jogo e com texto selecionado |
| Gestos | **Lógica testada, câmera falsa** — pendente com a sua mão |
| Chuva, noite, descanso de tela, humor | **Real aqui** (navegador) |
| Atualizador | **Real aqui** (cópia do pacote) — pendente no Windows |

## Fica para depois (sua escolha)

A parte "Casa" (ar e TV por infravermelho, sensores, câmera na porta, sensor da porta) fica para quando
os sensores existirem. O **modo férias** (luzes acendendo e apagando como se tivesse gente) não precisa de sensor e
pode entrar a qualquer momento.
