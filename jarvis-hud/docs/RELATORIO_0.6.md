# Relatório — JARVIS OS 0.6 (app do Windows, cenas da casa e HUD novo)

Feito em 13/11/2026, num contêiner Linux na nuvem, **sem Windows, sem as suas lâmpadas e sem a sua fechadura**.
O que depende do Windows foi testado com dublês (registro falso, plano de cena sem hardware). O teste real fica
para o chat do Windows ([`PROMPT_TESTE_WINDOWS.md`](PROMPT_TESTE_WINDOWS.md), fases 17 a 19).

## O que foi pedido e o que foi feito

| Pedido | Feito |
|---|---|
| "Programa de verdade" | `JARVIS.bat` / atalho **JARVIS** (`INSTALAR_ATALHOS.bat`) roda o núcleo com `pythonw` (sem console) e mostra um **ícone na bandeja** com o menu: abrir, falar, bloquear, iniciar com o Windows, pasta de dados, registro, sair. O HUD abre numa **janela própria** (Edge, Chrome ou Brave em modo app, com perfil próprio e música de entrada liberada). **Atalhos globais:** `Ctrl+Alt+J` traz o JARVIS e `Ctrl+Alt+Espaço` fala com ele; dá para trocar no `.env`. **Iniciar com o Windows:** no registro do usuário (sem administrador), pela bandeja ou em Configurações → Sistema; nesse caso só o ícone aparece. Rodar duas vezes não sobe um segundo núcleo: a janela existente vem para a frente. |
| "Cenas da casa" | Cinco cenas prontas, que juntam luzes de casa (Tuya), fita, volume, porta, resumo e agenda: **bom dia, modo cinema, modo foco, boa noite e saindo de casa**. Funcionam por voz, pelos botões do HUD e **por horário** (hora + todos os dias / dias úteis / fim de semana). |
| "Melhore o HUD e a interface, melhore tudo dela" | Barra do topo com indicador de conexão e botões de histórico, ajuda e tela cheia. **Coluna de ações à direita**: CENAS e CASA (acender, apagar, ver e trancar a porta, modo trancado) + comandos executados. **Coluna de informação à esquerda** sem corte na borda. **Histórico** (`L`) com a conversa e todos os avisos e ações. **Ajuda** (`?`) com atalhos e exemplos do que dizer. **Configurações em 6 abas** (Geral, Voz, Casa, Entrada, Agenda, Sistema). **Lembretes em destaque** no topo. **Tela de bloqueio** com relógio e data. **Layout para janelas menores** (sem a barra de comando esmagada nem painéis sobrepostos). |

### Regras das cenas

- **Rodar:** um botão de cena vira um plano **fixo** no núcleo, sem IA, e passa pelas mesmas ferramentas,
  confirmações e registros de um comando falado. Só existem as ações da lista (cena, luzes, fita, porta); qualquer
  outra é recusada.
- **Destrancar:** nenhuma cena nem botão destranca a porta. Uma rotina com "destrancar" no `permissions.json` é
  descartada ao carregar.
- **Confirmação:** "Saindo de casa" pede confirmação. No horário agendado ela **só avisa** (sem ninguém olhando,
  nada que precise de "sim" roda sozinho).
- **"Bom dia" e "boa noite":** só valem como frase inteira. "Bom dia, que horas são?" só diz a hora.
- **Recurso ausente** (ex.: sem lâmpadas Tuya): a etapa é pulada e contada ("1 pulada: recurso ausente"). Não conta
  como falha.
- **Com o JARVIS bloqueado:** a cena agendada roda, mas ele só cumprimenta. Clima, notícias e agenda não saem antes do
  rosto.
- **Agendamento:** uma vez por dia, até 3 minutos depois do horário. Se o PC estava desligado ou dormindo nesse
  intervalo, a cena fica para o próximo dia.
- **Mudar:** uma rotina com o mesmo id no `permissions.json` substitui a pronta; `"cenas_padrao": false` desliga
  todas.

### Correção encontrada no caminho

- **"desliga o PC em 10 minutos" ignorava o tempo:** usava 60 s. O pedido de confirmação mostrava 60 s, então nada
  desligava sem aviso. Agora o tempo dito vale (30 s a 10 min); acima disso ele recusa e explica.

## Testes executados aqui

- **Núcleo:** 318 testes automáticos passando (289 → 318). Os novos cobrem:
  - **atalhos:** só letras/dígitos ASCII e teclas nomeadas, exigem modificador;
  - **navegador:** escolha do navegador;
  - **iniciar com o Windows:** registro falso, liga/desliga; o comando gravado é fixo e nada do pedido entra nele;
  - **ponto de entrada:** `jarvis_app.pyw`;
  - **`/api/hud` e `/api/app`:** com e sem token;
  - **cenas:** prontas, substituição, nunca destrancar; 10 frases de cena; "bom dia, que horas são?"; etapa pulada
    sem Tuya; resumo falado;
  - **agendamento:** uma vez por dia, dias úteis, cena com confirmação só avisa, bloqueado só cumprimenta;
  - **botões do HUD pelo WebSocket:** plano fixo com confirmação; ações desconhecidas, destrancar e comandos
    inventados recusados; bloqueado não roda;
  - **desligar com tempo:** 6 frases.
- **HUD:** compila. O teste de navegador passou com **17 de 17**: as 14 verificações anteriores (adaptadas às abas)
  + cenas no controle rápido, botão de cena executando sem IA com resposta, ajuda pelo teclado.
- **Capturas:** antes e depois, em 1280×720 e numa janela estreita (760×900); tela de bloqueio; histórico;
  confirmação de cena; ajuda.

## Status

| Item | Status |
|---|---|
| Bandeja, janela própria, atalhos globais, instância única | **Escrito para o Windows; só a lógica foi testada aqui** — pendente no Windows (fase 17) |
| Iniciar com o Windows | **Dublê** (registro falso) — pendente no Windows |
| Cenas por voz, botão e horário | **Real aqui** (núcleo + HUD, fita no simulador) — com as lâmpadas e a fechadura: fase 18 |
| HUD novo | **Real aqui** (navegador headless) — FPS na RTX 2050 pendente (fase 19) |

## Pendências

1. Fases 17 a 19 no Windows, e as pendências da 0.5.3 (copiar/colar depois da correção das teclas).
2. Fases 15 e 16 com as lâmpadas Tuya e a fechadura do TCC.
3. Computer use com o modelo especializado, se aparecer na sua conta.

## Atualização 0.6.1 — cidade, qualidade e entrada só pelo rosto

Pedido: "melhorar a qualidade e o design dele inteiro, melhorar o design da cidade (está estranho, só as linhas
azuis); no desbloqueio não precisa piscar, ele abre só reconhecendo o rosto".

| Pedido | Feito |
|---|---|
| Cidade "só linhas azuis" | **Causa:** o OpenStreetMap de Itumbiara tem as ruas completas e quase nenhuma casa desenhada, e as ruas eram fitas de neon azul. **Agora**, mais perto da referência (ruas escuras, telhados cerâmicos, quadras arborizadas): ruas de asfalto com calçadas e só um fio de luz nas avenidas; **casas ilustrativas** de frente para as ruas reais (nunca em cima de rua, rio, praça ou prédio mapeado; só na área urbana; densas no centro, baixas nos bairros); prédios mapeados com **contorno ciano** (o que é dado real); árvores nos quintais e nas praças; rio com reflexo animado; faróis e lanternas de carros andando nas avenidas e rodovias; luzes de rua; nome dos pontos de referência (prefeitura, hospital, rodoviária…); varredura de radar dentro do anel. A nota do mapa diz o que é real e o que é ilustrativo. A cidade só é montada na primeira ida ao mapa (cerca de 0,1 s com o mapa de teste). |
| Qualidade geral | **Antisserrilhado** no perfil médio (SMAA; antes não havia nenhum). Perfil baixo com resolução cheia (era 75 %). **A qualidade automática não cai mais com a janela escondida:** só com a janela à vista e em foco, depois de 8 s abaixo de 24 fps (no seu relatório da 0.4, o FPS foi medido com o painel oculto: 3,7 FPS, o que derrubaria a qualidade sem você ver). A escolha da qualidade fica salva. Luzes de cidade do planeta mais nítidas (eram bolas borradas). Nota do mapa no canto, sem cobrir os nomes. |
| Entrar sem piscar | **Padrão agora: só o rosto.** Configurações → Entrada: "Entrar só pelo rosto, sem piscar" (ligado) e "Ligar a câmera sozinho na tela de bloqueio" (desligado; ligue para não precisar clicar em Iniciar). A variável `JARVIS_FACE_LIVENESS` do `.env` deixou de valer. |

**Atenção:** sem a piscada, uma foto boa do seu rosto pode abrir o JARVIS; a nota anti-foto ainda não é confiável
(72–83 % para fotos na 0.4). O JARVIS nunca abre a fechadura pelo rosto, e o PIN e a pausa depois de erros
continuam. Para mais segurança, volte a pedir a piscada nas Configurações.

### Testes da 0.6.1

- **Núcleo:** 319 testes. Novo teste: entrar sem piscar é o padrão, a piscada volta pelo HUD, valor inválido é
  ignorado.
- **Navegador:** 18 de 18 verificações. Nova: "mostra o mapa" monta a cidade com casas e mostra o aviso.
- **Entrada por rosto com câmera falsa** (fotos públicas, cadastro feito na 0.4):

  | Caso | Resultado |
  |---|---|
  | Outra pessoa | **recusada** (32 %) |
  | Dono, com outra foto, **sem piscar** | **entrou** (69 %) |
  | Piscada religada, foto parada | ficou em "Pisque uma vez" |
  | Câmera automática | ligou sem clique |

- **Cidade:** desenhada sobre um **mapa sintético** parecido com Itumbiara. O OpenStreetMap continua inacessível
  daqui: o acesso ao overpass-api.de foi liberado no ambiente, mas o servidor derruba a conexão. Falta ver com a
  Itumbiara real no seu PC (fase 20).
